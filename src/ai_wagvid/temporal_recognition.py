"""Uncertainty-first temporal recognition contracts underneath the interpretation layer.

This module describes what temporal/action-model adapters may emit. It is deliberately free of
D/E/final scores and official-result context. Exact element identity can remain unresolved while a
family is known. Human review can accept a candidate or explicitly override the ranked list.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .domain import Apparatus


class TemporalRecognitionError(ValueError):
    pass


class ResolutionState(StrEnum):
    UNKNOWN = "unknown"
    FAMILY_ONLY = "family-only"
    NEEDS_REVIEW = "needs-review"
    EXACT_ACCEPTED = "exact-accepted"


@dataclass(frozen=True)
class MultiViewIntervalRef:
    media_sha256: str
    camera_id: str
    start_ms: int
    end_ms: int
    evidence_digest: str

    def __post_init__(self) -> None:
        _require_sha256("media_sha256", self.media_sha256)
        _require_sha256("evidence_digest", self.evidence_digest)
        if not self.camera_id:
            raise TemporalRecognitionError("camera_id is required")
        if isinstance(self.start_ms, bool) or not isinstance(self.start_ms, int) or self.start_ms < 0:
            raise TemporalRecognitionError("start_ms must be non-negative integer")
        if isinstance(self.end_ms, bool) or not isinstance(self.end_ms, int) or self.end_ms <= self.start_ms:
            raise TemporalRecognitionError("end_ms must be integer after start_ms")

    @property
    def digest(self) -> str:
        return _stable_digest(asdict(self))


@dataclass(frozen=True)
class DistinguishingObservation:
    observation_id: str
    evidence_digest: str
    attribute: str
    value: str
    confidence_milli: int

    def __post_init__(self) -> None:
        if not self.observation_id or not self.attribute or not self.value:
            raise TemporalRecognitionError("observation identity/attribute/value are required")
        _require_sha256("observation evidence digest", self.evidence_digest)
        _require_milli("observation confidence", self.confidence_milli)

    @property
    def digest(self) -> str:
        return _stable_digest(asdict(self))


@dataclass(frozen=True)
class ElementAlternative:
    element_id: str
    family: str
    probability_milli: int
    distinguishing_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.element_id or not self.family:
            raise TemporalRecognitionError("element alternative ID/family are required")
        _require_milli("element probability", self.probability_milli)
        if self.probability_milli == 0:
            raise TemporalRecognitionError("ranked element alternative must have positive probability")
        if len(self.distinguishing_observation_ids) != len(set(self.distinguishing_observation_ids)):
            raise TemporalRecognitionError("distinguishing observation IDs must be unique")


@dataclass(frozen=True)
class CandidateProbabilityMass:
    alternatives: tuple[ElementAlternative, ...]
    unknown_ood_milli: int
    other_known_milli: int

    def __post_init__(self) -> None:
        _require_milli("unknown/OOD probability", self.unknown_ood_milli)
        _require_milli("other-known probability", self.other_known_milli)
        if not self.alternatives and self.other_known_milli:
            raise TemporalRecognitionError("other-known probability requires at least one ranked family context")
        element_ids = [item.element_id for item in self.alternatives]
        if len(element_ids) != len(set(element_ids)):
            raise TemporalRecognitionError("ranked element IDs must be unique")
        total = sum(item.probability_milli for item in self.alternatives) + self.unknown_ood_milli + self.other_known_milli
        if total != 1000:
            raise TemporalRecognitionError(f"candidate probability mass must sum to 1000, got {total}")
        expected = tuple(
            sorted(self.alternatives, key=lambda item: (-item.probability_milli, item.element_id))
        )
        if self.alternatives != expected:
            raise TemporalRecognitionError("element alternatives must use deterministic probability ranking")

    @property
    def top(self) -> ElementAlternative | None:
        return self.alternatives[0] if self.alternatives else None


@dataclass(frozen=True)
class TemporalElementCandidate:
    segment_id: str
    routine_id: str
    apparatus: Apparatus
    start_ms: int
    end_ms: int
    views: tuple[MultiViewIntervalRef, ...]
    observations: tuple[DistinguishingObservation, ...]
    probability: CandidateProbabilityMass
    model_bundle_digest: str
    model_config_digest: str
    perception_bundle_digest: str
    sequence_context_digest: str | None
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.segment_id or not self.routine_id:
            raise TemporalRecognitionError("segment_id and routine_id are required")
        if isinstance(self.start_ms, bool) or not isinstance(self.start_ms, int) or self.start_ms < 0:
            raise TemporalRecognitionError("segment start_ms must be non-negative integer")
        if isinstance(self.end_ms, bool) or not isinstance(self.end_ms, int) or self.end_ms <= self.start_ms:
            raise TemporalRecognitionError("segment end_ms must be after start_ms")
        if not self.views:
            raise TemporalRecognitionError("temporal candidate requires at least one source view")
        for view in self.views:
            if view.start_ms > self.start_ms or view.end_ms < self.end_ms:
                raise TemporalRecognitionError("source view must cover the canonical candidate interval")
        view_keys = [(item.media_sha256, item.camera_id) for item in self.views]
        if len(view_keys) != len(set(view_keys)):
            raise TemporalRecognitionError("candidate views must be unique per media/camera")
        observation_ids = [item.observation_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise TemporalRecognitionError("candidate observation IDs must be unique")
        known_observations = set(observation_ids)
        for alternative in self.probability.alternatives:
            missing = set(alternative.distinguishing_observation_ids) - known_observations
            if missing:
                raise TemporalRecognitionError(
                    "element alternative references unknown observations: " + ",".join(sorted(missing))
                )
        for label, value in (
            ("model_bundle_digest", self.model_bundle_digest),
            ("model_config_digest", self.model_config_digest),
            ("perception_bundle_digest", self.perception_bundle_digest),
        ):
            _require_sha256(label, value)
        if self.sequence_context_digest is not None:
            _require_sha256("sequence_context_digest", self.sequence_context_digest)
        _require_aware("candidate created_at", self.created_at)
        if len(self.limitations) != len(set(self.limitations)):
            raise TemporalRecognitionError("candidate limitations must be unique")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "segment_id": self.segment_id,
                "routine_id": self.routine_id,
                "apparatus": self.apparatus.value,
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
                "view_digests": [item.digest for item in self.views],
                "observation_digests": [item.digest for item in self.observations],
                "alternatives": [asdict(item) for item in self.probability.alternatives],
                "unknown_ood_milli": self.probability.unknown_ood_milli,
                "other_known_milli": self.probability.other_known_milli,
                "model_bundle_digest": self.model_bundle_digest,
                "model_config_digest": self.model_config_digest,
                "perception_bundle_digest": self.perception_bundle_digest,
                "sequence_context_digest": self.sequence_context_digest,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "limitations": list(self.limitations),
            }
        )


@dataclass(frozen=True)
class ResolutionPolicy:
    unknown_ood_at_least_milli: int = 500
    exact_top_at_least_milli: int = 800
    exact_margin_at_least_milli: int = 200
    family_mass_at_least_milli: int = 700
    automatic_exact_accept: bool = False

    def __post_init__(self) -> None:
        for label, value in (
            ("unknown_ood_at_least_milli", self.unknown_ood_at_least_milli),
            ("exact_top_at_least_milli", self.exact_top_at_least_milli),
            ("exact_margin_at_least_milli", self.exact_margin_at_least_milli),
            ("family_mass_at_least_milli", self.family_mass_at_least_milli),
        ):
            _require_milli(label, value)


@dataclass(frozen=True)
class CandidateResolution:
    state: ResolutionState
    segment_digest: str
    family: str | None
    element_id: str | None
    reason: str

    def __post_init__(self) -> None:
        _require_sha256("segment_digest", self.segment_digest)
        if self.state is ResolutionState.EXACT_ACCEPTED and not self.element_id:
            raise TemporalRecognitionError("exact accepted resolution requires element_id")
        if self.state is ResolutionState.FAMILY_ONLY and not self.family:
            raise TemporalRecognitionError("family-only resolution requires family")
        if self.state is ResolutionState.UNKNOWN and (self.family or self.element_id):
            raise TemporalRecognitionError("unknown resolution cannot claim family/element identity")


def resolve_candidate(
    candidate: TemporalElementCandidate,
    *,
    policy: ResolutionPolicy | None = None,
) -> CandidateResolution:
    policy = policy or ResolutionPolicy()
    mass = candidate.probability
    if mass.unknown_ood_milli >= policy.unknown_ood_at_least_milli:
        return CandidateResolution(
            state=ResolutionState.UNKNOWN,
            segment_digest=candidate.digest,
            family=None,
            element_id=None,
            reason="unknown-ood-threshold",
        )
    top = mass.top
    if top is None:
        return CandidateResolution(
            state=ResolutionState.UNKNOWN,
            segment_digest=candidate.digest,
            family=None,
            element_id=None,
            reason="no-ranked-element",
        )
    second_probability = mass.alternatives[1].probability_milli if len(mass.alternatives) > 1 else 0
    margin = top.probability_milli - second_probability
    if (
        policy.automatic_exact_accept
        and top.probability_milli >= policy.exact_top_at_least_milli
        and margin >= policy.exact_margin_at_least_milli
    ):
        return CandidateResolution(
            state=ResolutionState.EXACT_ACCEPTED,
            segment_digest=candidate.digest,
            family=top.family,
            element_id=top.element_id,
            reason="explicit-auto-exact-policy",
        )
    family_mass: dict[str, int] = {}
    for alternative in mass.alternatives:
        family_mass[alternative.family] = family_mass.get(alternative.family, 0) + alternative.probability_milli
    best_family, best_mass = max(family_mass.items(), key=lambda item: (item[1], item[0]))
    if best_mass >= policy.family_mass_at_least_milli:
        return CandidateResolution(
            state=ResolutionState.FAMILY_ONLY,
            segment_digest=candidate.digest,
            family=best_family,
            element_id=None,
            reason="family-mass-resolved-exact-unresolved",
        )
    return CandidateResolution(
        state=ResolutionState.NEEDS_REVIEW,
        segment_digest=candidate.digest,
        family=None,
        element_id=None,
        reason="exact-and-family-identity-unresolved",
    )


@dataclass(frozen=True)
class HumanElementDecision:
    decision_id: str
    segment_digest: str
    reviewer_id: str
    reviewer_qualification_ref: str
    chosen_element_id: str | None
    chosen_family: str | None
    reason_code: str
    notes: str
    decided_at: datetime
    model_candidate_override: bool

    def __post_init__(self) -> None:
        if (
            not self.decision_id
            or not self.reviewer_id
            or not self.reviewer_qualification_ref
            or not self.reason_code
            or not self.notes.strip()
        ):
            raise TemporalRecognitionError(
                "human element decision requires identity/reviewer/qualification/reason/notes"
            )
        _require_sha256("segment_digest", self.segment_digest)
        _require_aware("element decision time", self.decided_at)
        if self.chosen_element_id is None and self.chosen_family is None:
            raise TemporalRecognitionError("human decision must accept at least family or exact element")
        if self.chosen_element_id is not None and not self.chosen_family:
            raise TemporalRecognitionError("exact human element decision requires family")

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["decided_at"] = self.decided_at.astimezone(UTC).isoformat()
        return _stable_digest(payload)


def accept_human_element_decision(
    candidate: TemporalElementCandidate,
    *,
    decision_id: str,
    reviewer_id: str,
    reviewer_qualification_ref: str,
    chosen_element_id: str | None,
    chosen_family: str | None,
    reason_code: str,
    notes: str,
    decided_at: datetime,
) -> HumanElementDecision:
    ranked_by_id = {item.element_id: item for item in candidate.probability.alternatives}
    ranked_candidate = ranked_by_id.get(chosen_element_id) if chosen_element_id is not None else None
    if ranked_candidate is not None and chosen_family != ranked_candidate.family:
        raise TemporalRecognitionError(
            "human decision family must match the selected ranked element candidate"
        )
    override = chosen_element_id is not None and ranked_candidate is None
    return HumanElementDecision(
        decision_id=decision_id,
        segment_digest=candidate.digest,
        reviewer_id=reviewer_id,
        reviewer_qualification_ref=reviewer_qualification_ref,
        chosen_element_id=chosen_element_id,
        chosen_family=chosen_family,
        reason_code=reason_code,
        notes=notes,
        decided_at=decided_at,
        model_candidate_override=override,
    )


@dataclass(frozen=True)
class TemporalRecognitionBundle:
    bundle_id: str
    routine_id: str
    apparatus: Apparatus
    candidates: tuple[TemporalElementCandidate, ...]
    model_bundle_digest: str
    perception_bundle_digest: str
    created_at: datetime
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.bundle_id or not self.routine_id:
            raise TemporalRecognitionError("recognition bundle identity/routine are required")
        _require_sha256("model_bundle_digest", self.model_bundle_digest)
        _require_sha256("perception_bundle_digest", self.perception_bundle_digest)
        _require_aware("recognition bundle created_at", self.created_at)
        if not self.candidates:
            raise TemporalRecognitionError("recognition bundle requires at least one candidate")
        ids = [item.segment_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise TemporalRecognitionError("recognition bundle segment IDs must be unique")
        ordered = tuple(sorted(self.candidates, key=lambda item: (item.start_ms, item.end_ms, item.segment_id)))
        if ordered != self.candidates:
            raise TemporalRecognitionError("recognition candidates must be in chronological order")
        previous_end = -1
        for item in self.candidates:
            if item.routine_id != self.routine_id or item.apparatus is not self.apparatus:
                raise TemporalRecognitionError("recognition bundle cannot mix routine/apparatus")
            if item.model_bundle_digest != self.model_bundle_digest:
                raise TemporalRecognitionError("recognition bundle cannot mix model bundles")
            if item.perception_bundle_digest != self.perception_bundle_digest:
                raise TemporalRecognitionError("recognition bundle cannot mix perception bundles")
            if item.start_ms < previous_end:
                raise TemporalRecognitionError("recognized skill segments may not overlap")
            previous_end = item.end_ms
        if len(self.limitations) != len(set(self.limitations)):
            raise TemporalRecognitionError("recognition bundle limitations must be unique")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "bundle_id": self.bundle_id,
                "routine_id": self.routine_id,
                "apparatus": self.apparatus.value,
                "candidate_digests": [item.digest for item in self.candidates],
                "model_bundle_digest": self.model_bundle_digest,
                "perception_bundle_digest": self.perception_bundle_digest,
                "created_at": self.created_at.astimezone(UTC).isoformat(),
                "limitations": list(self.limitations),
            }
        )


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise TemporalRecognitionError(f"{label} must be lowercase SHA-256 hexadecimal")


def _require_milli(label: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise TemporalRecognitionError(f"{label} must be integer [0, 1000]")


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TemporalRecognitionError(f"{label} must be timezone-aware")
