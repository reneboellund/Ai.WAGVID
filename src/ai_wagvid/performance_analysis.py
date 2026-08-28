"""Evidence-backed coach/athlete performance analysis without causal diagnosis.

The module aggregates already reviewed observations. It preserves semantic boundaries between
observed facts, judging interpretations, patterns, coaching hypotheses and suggested training
focuses. Coach-set actionability/technical importance are never inferred from video confidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class PerformanceAnalysisError(ValueError):
    pass


class ObservationPolarity(StrEnum):
    STRENGTH = "strength"
    POINT_LOSS = "point-loss"
    NEUTRAL = "neutral"


class ObservationReviewState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CoachingHypothesisState(StrEnum):
    PROPOSED = "proposed"
    COACH_CONFIRMED = "coach-confirmed"
    COACH_REJECTED = "coach-rejected"


class TrainingFocusState(StrEnum):
    SUGGESTED = "suggested"
    COACH_SELECTED = "coach-selected"
    COACH_REJECTED = "coach-rejected"


@dataclass(frozen=True)
class PerformanceEvidenceRef:
    evidence_id: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise PerformanceAnalysisError("evidence_id is required")
        _require_sha256("evidence_digest", self.evidence_digest)

    @property
    def digest(self) -> str:
        return _stable_digest(asdict(self))


@dataclass(frozen=True)
class PerformanceObservation:
    observation_id: str
    athlete_group_id: str
    routine_id: str
    event_group_id: str | None
    apparatus: Apparatus
    category: str
    pattern_key: str
    phase: str | None
    element_family: str | None
    polarity: ObservationPolarity
    description: str
    evidence: tuple[PerformanceEvidenceRef, ...]
    confidence_milli: int
    review_state: ObservationReviewState
    source_digest: str
    point_loss_units: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.observation_id
            or not self.athlete_group_id
            or not self.routine_id
            or not self.category
            or not self.pattern_key
            or not self.description.strip()
        ):
            raise PerformanceAnalysisError("observation identity/group/category/pattern/description are required")
        _require_milli("confidence_milli", self.confidence_milli)
        _require_sha256("source_digest", self.source_digest)
        if not self.evidence:
            raise PerformanceAnalysisError("performance observation requires evidence")
        if len({item.digest for item in self.evidence}) != len(self.evidence):
            raise PerformanceAnalysisError("performance observation evidence must be unique")
        if self.point_loss_units is not None and self.point_loss_units < 0:
            raise PerformanceAnalysisError("point_loss_units cannot be negative")
        if self.polarity is ObservationPolarity.POINT_LOSS and self.point_loss_units is None:
            raise PerformanceAnalysisError("point-loss observation requires estimated point-loss units")
        if self.polarity is not ObservationPolarity.POINT_LOSS and self.point_loss_units not in {None, 0}:
            raise PerformanceAnalysisError("non-point-loss observation cannot carry point-loss units")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["apparatus"] = self.apparatus.value
        payload["polarity"] = self.polarity.value
        payload["review_state"] = self.review_state.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class TechnicalPattern:
    pattern_id: str
    athlete_group_id: str
    apparatus: Apparatus
    pattern_key: str
    polarity: ObservationPolarity
    category: str
    observation_ids: tuple[str, ...]
    routine_ids: tuple[str, ...]
    occurrence_count: int
    routine_count: int
    evidence_count: int
    point_loss_units: int | None
    confidence_floor_milli: int

    def __post_init__(self) -> None:
        if not self.pattern_id or not self.pattern_key or not self.category:
            raise PerformanceAnalysisError("pattern identity/key/category are required")
        if self.occurrence_count != len(self.observation_ids):
            raise PerformanceAnalysisError("pattern occurrence_count does not match observations")
        if self.routine_count != len(self.routine_ids):
            raise PerformanceAnalysisError("pattern routine_count does not match routine IDs")
        _require_milli("confidence_floor_milli", self.confidence_floor_milli)
        if self.point_loss_units is not None and self.point_loss_units < 0:
            raise PerformanceAnalysisError("pattern point loss cannot be negative")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["apparatus"] = self.apparatus.value
        payload["polarity"] = self.polarity.value
        return _stable_digest(payload)


@dataclass(frozen=True)
class CoachPriorityInput:
    pattern_digest: str
    coach_id: str
    technical_importance_milli: int
    actionability_milli: int
    rationale: str

    def __post_init__(self) -> None:
        _require_sha256("pattern_digest", self.pattern_digest)
        if not self.coach_id or not self.rationale.strip():
            raise PerformanceAnalysisError("coach priority input requires coach and rationale")
        _require_milli("technical_importance_milli", self.technical_importance_milli)
        _require_milli("actionability_milli", self.actionability_milli)


_PRIORITY_DIMENSIONS = {
    "point_loss_units",
    "routine_count",
    "occurrence_count",
    "confidence_floor_milli",
    "technical_importance_milli",
    "actionability_milli",
}


@dataclass(frozen=True)
class PriorityPolicy:
    dimension_order: tuple[str, ...] = (
        "point_loss_units",
        "routine_count",
        "occurrence_count",
        "confidence_floor_milli",
        "technical_importance_milli",
        "actionability_milli",
    )

    def __post_init__(self) -> None:
        if not self.dimension_order:
            raise PerformanceAnalysisError("priority dimension order cannot be empty")
        if len(self.dimension_order) != len(set(self.dimension_order)):
            raise PerformanceAnalysisError("priority dimensions must be unique")
        unknown = set(self.dimension_order) - _PRIORITY_DIMENSIONS
        if unknown:
            raise PerformanceAnalysisError(
                "unknown priority dimension(s): " + ", ".join(sorted(unknown))
            )


@dataclass(frozen=True)
class PriorityEntry:
    priority_number: int
    pattern_digest: str
    pattern_key: str
    dimensions: tuple[tuple[str, int], ...]
    coach_id: str
    coach_rationale: str

    def __post_init__(self) -> None:
        if self.priority_number < 1:
            raise PerformanceAnalysisError("priority number must be positive")
        _require_sha256("pattern_digest", self.pattern_digest)


@dataclass(frozen=True)
class CoachingHypothesis:
    hypothesis_id: str
    pattern_digest: str
    text: str
    created_by: str
    created_at: datetime
    state: CoachingHypothesisState = CoachingHypothesisState.PROPOSED
    coach_review_id: str | None = None

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.text.strip() or not self.created_by:
            raise PerformanceAnalysisError("coaching hypothesis identity/text/author are required")
        _require_sha256("pattern_digest", self.pattern_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise PerformanceAnalysisError("hypothesis created_at must be timezone-aware")
        if self.state is CoachingHypothesisState.PROPOSED and self.coach_review_id is not None:
            raise PerformanceAnalysisError("proposed hypothesis cannot claim a coach review")
        if self.state is not CoachingHypothesisState.PROPOSED and not self.coach_review_id:
            raise PerformanceAnalysisError("confirmed/rejected hypothesis requires coach review ID")

    @property
    def semantic_layer(self) -> str:
        return "coaching-hypothesis"


@dataclass(frozen=True)
class TrainingFocusSuggestion:
    focus_id: str
    pattern_digest: str
    text: str
    created_by: str
    created_at: datetime
    state: TrainingFocusState = TrainingFocusState.SUGGESTED
    coach_review_id: str | None = None

    def __post_init__(self) -> None:
        if not self.focus_id or not self.text.strip() or not self.created_by:
            raise PerformanceAnalysisError("training focus identity/text/author are required")
        _require_sha256("pattern_digest", self.pattern_digest)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise PerformanceAnalysisError("training focus created_at must be timezone-aware")
        if self.state is TrainingFocusState.SUGGESTED and self.coach_review_id is not None:
            raise PerformanceAnalysisError("suggested training focus cannot claim a coach review")
        if self.state is not TrainingFocusState.SUGGESTED and not self.coach_review_id:
            raise PerformanceAnalysisError("selected/rejected training focus requires coach review ID")

    @property
    def semantic_layer(self) -> str:
        return "suggested-training-focus"


@dataclass(frozen=True)
class PerformanceReport:
    report_id: str
    athlete_group_id: str
    generated_at: datetime
    routine_ids: tuple[str, ...]
    strengths: tuple[PerformanceObservation, ...]
    point_loss_observations: tuple[PerformanceObservation, ...]
    neutral_observations: tuple[PerformanceObservation, ...]
    patterns: tuple[TechnicalPattern, ...]
    priorities: tuple[PriorityEntry, ...]
    coaching_hypotheses: tuple[CoachingHypothesis, ...] = ()
    training_focuses: tuple[TrainingFocusSuggestion, ...] = ()

    def __post_init__(self) -> None:
        if not self.report_id or not self.athlete_group_id:
            raise PerformanceAnalysisError("report and athlete group identity are required")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise PerformanceAnalysisError("report generated_at must be timezone-aware")
        if len(self.routine_ids) != len(set(self.routine_ids)):
            raise PerformanceAnalysisError("report routine IDs must be unique")
        pattern_digests = {item.digest for item in self.patterns}
        for item in self.priorities:
            if item.pattern_digest not in pattern_digests:
                raise PerformanceAnalysisError("priority references pattern outside report")
        for item in (*self.coaching_hypotheses, *self.training_focuses):
            if item.pattern_digest not in pattern_digests:
                raise PerformanceAnalysisError("coach layer references pattern outside report")

    def normalized_dict(self) -> dict:
        return {
            "schema": "ai.wagvid.performance-report.v1",
            "report_id": self.report_id,
            "athlete_group_id": self.athlete_group_id,
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "routine_ids": list(self.routine_ids),
            "observed_facts": {
                "strengths": [_observation_payload(item) for item in self.strengths],
                "point_loss": [_observation_payload(item) for item in self.point_loss_observations],
                "neutral": [_observation_payload(item) for item in self.neutral_observations],
            },
            "patterns": [_pattern_payload(item) for item in self.patterns],
            "priorities": [
                {
                    **asdict(item),
                    "dimensions": [list(value) for value in item.dimensions],
                }
                for item in self.priorities
            ],
            "coaching_hypotheses": [
                {
                    **asdict(item),
                    "state": item.state.value,
                    "created_at": item.created_at.astimezone(UTC).isoformat(),
                    "semantic_layer": item.semantic_layer,
                }
                for item in self.coaching_hypotheses
            ],
            "suggested_training_focuses": [
                {
                    **asdict(item),
                    "state": item.state.value,
                    "created_at": item.created_at.astimezone(UTC).isoformat(),
                    "semantic_layer": item.semantic_layer,
                }
                for item in self.training_focuses
            ],
        }

    def normalized_json(self) -> str:
        return json.dumps(self.normalized_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalized_json().encode()).hexdigest()


def build_patterns(
    observations: Iterable[PerformanceObservation],
    *,
    minimum_occurrences: int = 2,
) -> tuple[TechnicalPattern, ...]:
    if minimum_occurrences < 1:
        raise PerformanceAnalysisError("minimum_occurrences must be positive")
    items = tuple(observations)
    if any(item.review_state is not ObservationReviewState.ACCEPTED for item in items):
        raise PerformanceAnalysisError("patterns may only use accepted observations")
    groups: dict[tuple[str, str, str, str, str], list[PerformanceObservation]] = {}
    for item in items:
        key = (
            item.athlete_group_id,
            item.apparatus.value,
            item.pattern_key,
            item.polarity.value,
            item.category,
        )
        groups.setdefault(key, []).append(item)
    patterns = []
    for key, group in sorted(groups.items()):
        if len(group) < minimum_occurrences:
            continue
        group.sort(key=lambda item: (item.routine_id, item.observation_id))
        routine_ids = tuple(sorted({item.routine_id for item in group}))
        point_loss = (
            sum(item.point_loss_units or 0 for item in group)
            if group[0].polarity is ObservationPolarity.POINT_LOSS
            else None
        )
        pattern_seed = {
            "athlete_group_id": key[0],
            "apparatus": key[1],
            "pattern_key": key[2],
            "polarity": key[3],
            "category": key[4],
            "observation_digests": [item.digest for item in group],
        }
        pattern_id = f"pattern:{_stable_digest(pattern_seed)[:24]}"
        patterns.append(
            TechnicalPattern(
                pattern_id=pattern_id,
                athlete_group_id=key[0],
                apparatus=Apparatus(key[1]),
                pattern_key=key[2],
                polarity=ObservationPolarity(key[3]),
                category=key[4],
                observation_ids=tuple(item.observation_id for item in group),
                routine_ids=routine_ids,
                occurrence_count=len(group),
                routine_count=len(routine_ids),
                evidence_count=sum(len(item.evidence) for item in group),
                point_loss_units=point_loss,
                confidence_floor_milli=min(item.confidence_milli for item in group),
            )
        )
    return tuple(sorted(patterns, key=lambda item: (item.apparatus.value, item.pattern_key, item.pattern_id)))


def rank_priorities(
    patterns: Iterable[TechnicalPattern],
    coach_inputs: Iterable[CoachPriorityInput],
    *,
    policy: PriorityPolicy | None = None,
) -> tuple[PriorityEntry, ...]:
    policy = policy or PriorityPolicy()
    pattern_items = tuple(patterns)
    inputs = tuple(coach_inputs)
    input_map = {item.pattern_digest: item for item in inputs}
    if len(input_map) != len(inputs):
        raise PerformanceAnalysisError("coach priority inputs must have unique pattern digests")
    candidates = []
    for pattern in pattern_items:
        if pattern.polarity is not ObservationPolarity.POINT_LOSS:
            continue
        coach = input_map.get(pattern.digest)
        if coach is None:
            raise PerformanceAnalysisError(
                f"point-loss pattern requires coach priority input: {pattern.pattern_key}"
            )
        dimensions = {
            "point_loss_units": pattern.point_loss_units or 0,
            "routine_count": pattern.routine_count,
            "occurrence_count": pattern.occurrence_count,
            "confidence_floor_milli": pattern.confidence_floor_milli,
            "technical_importance_milli": coach.technical_importance_milli,
            "actionability_milli": coach.actionability_milli,
        }
        sort_key = tuple(dimensions[name] for name in policy.dimension_order)
        candidates.append((sort_key, pattern, coach, dimensions))
    candidates.sort(
        key=lambda item: (
            tuple(-value for value in item[0]),
            item[1].pattern_key,
            item[1].digest,
        )
    )
    return tuple(
        PriorityEntry(
            priority_number=index + 1,
            pattern_digest=pattern.digest,
            pattern_key=pattern.pattern_key,
            dimensions=tuple((name, dimensions[name]) for name in policy.dimension_order),
            coach_id=coach.coach_id,
            coach_rationale=coach.rationale,
        )
        for index, (_, pattern, coach, dimensions) in enumerate(candidates)
    )


def build_performance_report(
    *,
    report_id: str,
    athlete_group_id: str,
    generated_at: datetime,
    observations: Iterable[PerformanceObservation],
    patterns: Iterable[TechnicalPattern],
    priorities: Iterable[PriorityEntry],
    coaching_hypotheses: Iterable[CoachingHypothesis] = (),
    training_focuses: Iterable[TrainingFocusSuggestion] = (),
) -> PerformanceReport:
    accepted = tuple(observations)
    if any(item.review_state is not ObservationReviewState.ACCEPTED for item in accepted):
        raise PerformanceAnalysisError("performance report may only contain accepted observations")
    if any(item.athlete_group_id != athlete_group_id for item in accepted):
        raise PerformanceAnalysisError("performance report cannot mix athlete group IDs")
    return PerformanceReport(
        report_id=report_id,
        athlete_group_id=athlete_group_id,
        generated_at=generated_at,
        routine_ids=tuple(sorted({item.routine_id for item in accepted})),
        strengths=tuple(
            sorted(
                (item for item in accepted if item.polarity is ObservationPolarity.STRENGTH),
                key=lambda item: (item.routine_id, item.observation_id),
            )
        ),
        point_loss_observations=tuple(
            sorted(
                (item for item in accepted if item.polarity is ObservationPolarity.POINT_LOSS),
                key=lambda item: (item.routine_id, item.observation_id),
            )
        ),
        neutral_observations=tuple(
            sorted(
                (item for item in accepted if item.polarity is ObservationPolarity.NEUTRAL),
                key=lambda item: (item.routine_id, item.observation_id),
            )
        ),
        patterns=tuple(patterns),
        priorities=tuple(priorities),
        coaching_hypotheses=tuple(coaching_hypotheses),
        training_focuses=tuple(training_focuses),
    )


def _observation_payload(item: PerformanceObservation) -> dict:
    return {
        "observation_id": item.observation_id,
        "athlete_group_id": item.athlete_group_id,
        "routine_id": item.routine_id,
        "event_group_id": item.event_group_id,
        "apparatus": item.apparatus.value,
        "category": item.category,
        "pattern_key": item.pattern_key,
        "phase": item.phase,
        "element_family": item.element_family,
        "polarity": item.polarity.value,
        "description": item.description,
        "evidence": [asdict(value) for value in item.evidence],
        "confidence_milli": item.confidence_milli,
        "review_state": item.review_state.value,
        "source_digest": item.source_digest,
        "point_loss_units": item.point_loss_units,
        "semantic_layer": "observed-fact",
    }


def _pattern_payload(item: TechnicalPattern) -> dict:
    payload = asdict(item)
    payload["apparatus"] = item.apparatus.value
    payload["polarity"] = item.polarity.value
    payload["semantic_layer"] = "pattern"
    return payload


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise PerformanceAnalysisError(f"{label} must be integer [0, 1000]")


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PerformanceAnalysisError(f"{label} must be lowercase SHA-256 hexadecimal")
