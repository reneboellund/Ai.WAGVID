"""Longitudinal aggregation of accepted Ai.WAGVID performance observations.

Trends are descriptive summaries over immutable routine analysis revisions. They never compare
athletes, diagnose causes or hide composition/rulepack changes. A trend becomes directly
comparable only when the selected snapshots use one rulepack and one apparatus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from statistics import median
from typing import Iterable

from .domain import Apparatus
from .performance_analysis import (
    ObservationPolarity,
    ObservationReviewState,
    PerformanceAnalysisError,
    PerformanceObservation,
)


class TrendDirection(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"
    INSUFFICIENT_DATA = "insufficient-data"
    NOT_COMPARABLE = "not-comparable"


@dataclass(frozen=True)
class RoutinePerformanceSnapshot:
    snapshot_id: str
    athlete_group_id: str
    routine_id: str
    event_group_id: str | None
    occurred_at: datetime
    apparatus: Apparatus
    analysis_revision_id: str
    analysis_revision_digest: str
    rulepack_id: str
    rulepack_digest: str
    model_bundle_digest: str
    composition_signature: str
    observations: tuple[PerformanceObservation, ...]

    def __post_init__(self) -> None:
        if (
            not self.snapshot_id
            or not self.athlete_group_id
            or not self.routine_id
            or not self.analysis_revision_id
            or not self.rulepack_id
            or not self.composition_signature
        ):
            raise PerformanceAnalysisError(
                "snapshot identity, athlete/routine/revision/rulepack/composition are required"
            )
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise PerformanceAnalysisError("snapshot occurred_at must be timezone-aware")
        _require_sha256("analysis_revision_digest", self.analysis_revision_digest)
        _require_sha256("rulepack_digest", self.rulepack_digest)
        _require_sha256("model_bundle_digest", self.model_bundle_digest)
        if not self.observations:
            raise PerformanceAnalysisError("snapshot requires accepted observations")
        for observation in self.observations:
            if observation.review_state is not ObservationReviewState.ACCEPTED:
                raise PerformanceAnalysisError("snapshot may only contain accepted observations")
            if observation.athlete_group_id != self.athlete_group_id:
                raise PerformanceAnalysisError("snapshot cannot mix athlete group IDs")
            if observation.routine_id != self.routine_id:
                raise PerformanceAnalysisError("snapshot observation routine does not match snapshot")
            if observation.apparatus != self.apparatus:
                raise PerformanceAnalysisError("snapshot observation apparatus does not match snapshot")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "snapshot_id": self.snapshot_id,
                "athlete_group_id": self.athlete_group_id,
                "routine_id": self.routine_id,
                "event_group_id": self.event_group_id,
                "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
                "apparatus": self.apparatus.value,
                "analysis_revision_id": self.analysis_revision_id,
                "analysis_revision_digest": self.analysis_revision_digest,
                "rulepack_id": self.rulepack_id,
                "rulepack_digest": self.rulepack_digest,
                "model_bundle_digest": self.model_bundle_digest,
                "composition_signature": self.composition_signature,
                "observation_digests": [item.digest for item in self.observations],
            }
        )


@dataclass(frozen=True)
class TrendPolicy:
    minimum_points: int = 3
    material_change_units: int = 1

    def __post_init__(self) -> None:
        if self.minimum_points < 2:
            raise PerformanceAnalysisError("trend minimum_points must be at least 2")
        if self.material_change_units < 0:
            raise PerformanceAnalysisError("material_change_units cannot be negative")


@dataclass(frozen=True)
class LongitudinalMetricPoint:
    snapshot_digest: str
    routine_id: str
    occurred_at: datetime
    value_units: int
    occurrence_count: int
    composition_signature: str
    analysis_revision_id: str
    rulepack_digest: str
    model_bundle_digest: str

    def __post_init__(self) -> None:
        _require_sha256("snapshot_digest", self.snapshot_digest)
        _require_sha256("rulepack_digest", self.rulepack_digest)
        _require_sha256("model_bundle_digest", self.model_bundle_digest)
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise PerformanceAnalysisError("metric point occurred_at must be timezone-aware")
        if self.value_units < 0 or self.occurrence_count < 0:
            raise PerformanceAnalysisError("metric point values cannot be negative")


@dataclass(frozen=True)
class CategoryTrend:
    athlete_group_id: str
    apparatus: Apparatus
    category: str
    polarity: ObservationPolarity
    points: tuple[LongitudinalMetricPoint, ...]
    direction: TrendDirection
    earlier_median_units: int | float | None
    later_median_units: int | float | None
    delta_units: int | float | None
    composition_changed: bool
    rulepack_changed: bool
    model_bundle_changed: bool
    comparability_reasons: tuple[str, ...]

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "athlete_group_id": self.athlete_group_id,
                "apparatus": self.apparatus.value,
                "category": self.category,
                "polarity": self.polarity.value,
                "points": [
                    {
                        **asdict(item),
                        "occurred_at": item.occurred_at.astimezone(UTC).isoformat(),
                    }
                    for item in self.points
                ],
                "direction": self.direction.value,
                "earlier_median_units": self.earlier_median_units,
                "later_median_units": self.later_median_units,
                "delta_units": self.delta_units,
                "composition_changed": self.composition_changed,
                "rulepack_changed": self.rulepack_changed,
                "model_bundle_changed": self.model_bundle_changed,
                "comparability_reasons": list(self.comparability_reasons),
            }
        )


@dataclass(frozen=True)
class LongitudinalReport:
    report_id: str
    athlete_group_id: str
    apparatus: Apparatus
    generated_at: datetime
    snapshot_digests: tuple[str, ...]
    trends: tuple[CategoryTrend, ...]

    def __post_init__(self) -> None:
        if not self.report_id or not self.athlete_group_id:
            raise PerformanceAnalysisError("longitudinal report identity and athlete group are required")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise PerformanceAnalysisError("longitudinal report generated_at must be timezone-aware")
        for digest in self.snapshot_digests:
            _require_sha256("snapshot digest", digest)
        if len(self.snapshot_digests) != len(set(self.snapshot_digests)):
            raise PerformanceAnalysisError("longitudinal report snapshot digests must be unique")
        if any(item.athlete_group_id != self.athlete_group_id for item in self.trends):
            raise PerformanceAnalysisError("longitudinal report cannot mix athletes")
        if any(item.apparatus != self.apparatus for item in self.trends):
            raise PerformanceAnalysisError("longitudinal report cannot mix apparatus")

    def normalized_dict(self) -> dict:
        return {
            "schema": "ai.wagvid.longitudinal-report.v1",
            "report_id": self.report_id,
            "athlete_group_id": self.athlete_group_id,
            "apparatus": self.apparatus.value,
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "snapshot_digests": list(self.snapshot_digests),
            "trends": [
                {
                    "athlete_group_id": item.athlete_group_id,
                    "apparatus": item.apparatus.value,
                    "category": item.category,
                    "polarity": item.polarity.value,
                    "points": [
                        {
                            **asdict(point),
                            "occurred_at": point.occurred_at.astimezone(UTC).isoformat(),
                        }
                        for point in item.points
                    ],
                    "direction": item.direction.value,
                    "earlier_median_units": item.earlier_median_units,
                    "later_median_units": item.later_median_units,
                    "delta_units": item.delta_units,
                    "composition_changed": item.composition_changed,
                    "rulepack_changed": item.rulepack_changed,
                    "model_bundle_changed": item.model_bundle_changed,
                    "comparability_reasons": list(item.comparability_reasons),
                    "trend_digest": item.digest,
                }
                for item in self.trends
            ],
        }

    def normalized_json(self) -> str:
        return json.dumps(self.normalized_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalized_json().encode()).hexdigest()


def build_category_trends(
    snapshots: Iterable[RoutinePerformanceSnapshot],
    *,
    policy: TrendPolicy = TrendPolicy(),
) -> tuple[CategoryTrend, ...]:
    items = _validate_snapshot_series(tuple(snapshots))
    if not items:
        return ()
    athlete = items[0].athlete_group_id
    apparatus = items[0].apparatus
    categories = sorted(
        {
            (observation.category, observation.polarity)
            for snapshot in items
            for observation in snapshot.observations
        },
        key=lambda value: (value[0], value[1].value),
    )
    result = []
    for category, polarity in categories:
        points = tuple(
            _metric_point(snapshot, category=category, polarity=polarity)
            for snapshot in items
            if any(
                observation.category == category and observation.polarity is polarity
                for observation in snapshot.observations
            )
        )
        if not points:
            continue
        rulepacks = {point.rulepack_digest for point in points}
        models = {point.model_bundle_digest for point in points}
        compositions = {point.composition_signature for point in points}
        rulepack_changed = len(rulepacks) > 1
        model_changed = len(models) > 1
        composition_changed = len(compositions) > 1
        reasons: list[str] = []
        if rulepack_changed:
            reasons.append("rulepack-changed")
        if len(points) < policy.minimum_points:
            reasons.append(f"insufficient-points:{len(points)}<{policy.minimum_points}")

        if rulepack_changed:
            direction = TrendDirection.NOT_COMPARABLE
            earlier = later = delta = None
        elif len(points) < policy.minimum_points:
            direction = TrendDirection.INSUFFICIENT_DATA
            earlier = later = delta = None
        else:
            split = len(points) // 2
            earlier_values = [point.value_units for point in points[:split]]
            later_values = [point.value_units for point in points[split:]]
            earlier = median(earlier_values)
            later = median(later_values)
            delta = later - earlier
            if abs(delta) < policy.material_change_units:
                direction = TrendDirection.STABLE
            elif polarity is ObservationPolarity.POINT_LOSS:
                direction = TrendDirection.IMPROVING if delta < 0 else TrendDirection.WORSENING
            elif polarity is ObservationPolarity.STRENGTH:
                direction = TrendDirection.IMPROVING if delta > 0 else TrendDirection.WORSENING
            else:
                direction = TrendDirection.STABLE
        result.append(
            CategoryTrend(
                athlete_group_id=athlete,
                apparatus=apparatus,
                category=category,
                polarity=polarity,
                points=points,
                direction=direction,
                earlier_median_units=earlier,
                later_median_units=later,
                delta_units=delta,
                composition_changed=composition_changed,
                rulepack_changed=rulepack_changed,
                model_bundle_changed=model_changed,
                comparability_reasons=tuple(reasons),
            )
        )
    return tuple(result)


def build_longitudinal_report(
    *,
    report_id: str,
    generated_at: datetime,
    snapshots: Iterable[RoutinePerformanceSnapshot],
    policy: TrendPolicy = TrendPolicy(),
) -> LongitudinalReport:
    items = _validate_snapshot_series(tuple(snapshots))
    if not items:
        raise PerformanceAnalysisError("longitudinal report requires at least one snapshot")
    trends = build_category_trends(items, policy=policy)
    return LongitudinalReport(
        report_id=report_id,
        athlete_group_id=items[0].athlete_group_id,
        apparatus=items[0].apparatus,
        generated_at=generated_at,
        snapshot_digests=tuple(item.digest for item in items),
        trends=trends,
    )


def _validate_snapshot_series(
    snapshots: tuple[RoutinePerformanceSnapshot, ...],
) -> tuple[RoutinePerformanceSnapshot, ...]:
    if not snapshots:
        return ()
    athlete_ids = {item.athlete_group_id for item in snapshots}
    apparatuses = {item.apparatus for item in snapshots}
    if len(athlete_ids) != 1:
        raise PerformanceAnalysisError("longitudinal analysis cannot compare different athletes")
    if len(apparatuses) != 1:
        raise PerformanceAnalysisError("longitudinal trend series must use one apparatus")
    snapshot_ids = [item.snapshot_id for item in snapshots]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise PerformanceAnalysisError("snapshot IDs must be unique")
    revision_digests = [item.analysis_revision_digest for item in snapshots]
    if len(revision_digests) != len(set(revision_digests)):
        raise PerformanceAnalysisError("analysis revision digests must be unique")
    # More than one immutable revision of the same routine may coexist in storage, but a
    # single trend series must choose exactly one revision per routine explicitly.
    routine_ids = [item.routine_id for item in snapshots]
    if len(routine_ids) != len(set(routine_ids)):
        raise PerformanceAnalysisError(
            "trend series cannot silently choose between multiple revisions of one routine"
        )
    return tuple(sorted(snapshots, key=lambda item: (item.occurred_at, item.routine_id, item.snapshot_id)))


def _metric_point(
    snapshot: RoutinePerformanceSnapshot,
    *,
    category: str,
    polarity: ObservationPolarity,
) -> LongitudinalMetricPoint:
    matching = tuple(
        observation
        for observation in snapshot.observations
        if observation.category == category and observation.polarity is polarity
    )
    if polarity is ObservationPolarity.POINT_LOSS:
        value_units = sum(item.point_loss_units or 0 for item in matching)
    else:
        # Strength/neutral trends are count-based unless a future reviewed metric contract
        # supplies a domain-specific quantitative value. Do not invent a quality score.
        value_units = len(matching)
    return LongitudinalMetricPoint(
        snapshot_digest=snapshot.digest,
        routine_id=snapshot.routine_id,
        occurred_at=snapshot.occurred_at,
        value_units=value_units,
        occurrence_count=len(matching),
        composition_signature=snapshot.composition_signature,
        analysis_revision_id=snapshot.analysis_revision_id,
        rulepack_digest=snapshot.rulepack_digest,
        model_bundle_digest=snapshot.model_bundle_digest,
    )


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise PerformanceAnalysisError(f"{label} must be lowercase SHA-256 hexadecimal")
