import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.longitudinal import (
    RoutinePerformanceSnapshot,
    TrendDirection,
    TrendPolicy,
    build_category_trends,
    build_longitudinal_report,
)
from ai_wagvid.performance_analysis import (
    ObservationPolarity,
    ObservationReviewState,
    PerformanceAnalysisError,
    PerformanceEvidenceRef,
    PerformanceObservation,
)

T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def obs(
    observation_id: str,
    routine_id: str,
    *,
    athlete: str = "athlete-1",
    category: str = "landing",
    polarity: ObservationPolarity = ObservationPolarity.POINT_LOSS,
    loss: int | None = 2,
    state: ObservationReviewState = ObservationReviewState.ACCEPTED,
) -> PerformanceObservation:
    return PerformanceObservation(
        observation_id=observation_id,
        athlete_group_id=athlete,
        routine_id=routine_id,
        event_group_id=f"event-{routine_id}",
        apparatus=Apparatus.BB,
        category=category,
        pattern_key=f"{category}-pattern",
        phase="fixture-phase",
        element_family="fixture-family",
        polarity=polarity,
        description="Reviewed fixture observation",
        evidence=(PerformanceEvidenceRef(f"ev-{observation_id}", sha(f"ev:{observation_id}")),),
        confidence_milli=900,
        review_state=state,
        source_digest=sha(f"source:{observation_id}"),
        point_loss_units=loss,
    )


def snapshot(
    index: int,
    observations: tuple[PerformanceObservation, ...],
    *,
    athlete: str = "athlete-1",
    routine_id: str | None = None,
    rulepack_digest: str | None = None,
    model_digest: str | None = None,
    composition: str = "composition-A",
    revision_id: str | None = None,
) -> RoutinePerformanceSnapshot:
    routine = routine_id or f"routine-{index}"
    return RoutinePerformanceSnapshot(
        snapshot_id=f"snapshot-{index}",
        athlete_group_id=athlete,
        routine_id=routine,
        event_group_id=f"event-{index}",
        occurred_at=T0 + timedelta(days=index),
        apparatus=Apparatus.BB,
        analysis_revision_id=revision_id or f"revision-{index}",
        analysis_revision_digest=sha(f"revision:{revision_id or index}"),
        rulepack_id="fixture-rulepack@v1",
        rulepack_digest=rulepack_digest or sha("rulepack-A"),
        model_bundle_digest=model_digest or sha("model-A"),
        composition_signature=composition,
        observations=observations,
    )


def test_point_loss_disappearance_contributes_zero_and_can_show_improvement():
    series = (
        snapshot(0, (obs("l0a", "routine-0", loss=4), obs("other0", "routine-0", category="other", loss=1))),
        snapshot(1, (obs("l1a", "routine-1", loss=3),)),
        snapshot(2, (obs("other2", "routine-2", category="other", loss=1),)),
        snapshot(3, (obs("other3", "routine-3", category="other", loss=1),)),
    )
    trend = next(
        item for item in build_category_trends(series) if item.category == "landing"
    )
    assert [point.value_units for point in trend.points] == [4, 3, 0, 0]
    assert trend.earlier_median_units == 3.5
    assert trend.later_median_units == 0
    assert trend.direction is TrendDirection.IMPROVING


def test_increasing_point_loss_is_worsening_and_flat_series_is_stable():
    worsening_series = tuple(
        snapshot(
            index,
            (obs(f"l{index}", f"routine-{index}", loss=loss),),
        )
        for index, loss in enumerate((1, 1, 3, 4))
    )
    trend = build_category_trends(worsening_series)[0]
    assert trend.direction is TrendDirection.WORSENING
    assert trend.delta_units > 0

    stable_series = tuple(
        snapshot(
            index + 10,
            (obs(f"s{index}", f"routine-{index + 10}", loss=2),),
        )
        for index in range(4)
    )
    stable = build_category_trends(stable_series)[0]
    assert stable.direction is TrendDirection.STABLE
    assert stable.delta_units == 0


def test_strength_trend_uses_occurrence_count_not_a_fabricated_quality_score():
    series = (
        snapshot(20, (obs("x20", "routine-20", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),)),
        snapshot(21, (obs("x21", "routine-21", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),)),
        snapshot(
            22,
            (
                obs("x22a", "routine-22", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),
                obs("x22b", "routine-22", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),
            ),
        ),
        snapshot(
            23,
            (
                obs("x23a", "routine-23", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),
                obs("x23b", "routine-23", category="control", polarity=ObservationPolarity.STRENGTH, loss=None),
            ),
        ),
    )
    trend = build_category_trends(series)[0]
    assert [point.value_units for point in trend.points] == [1, 1, 2, 2]
    assert trend.direction is TrendDirection.IMPROVING


def test_rulepack_change_blocks_direction_instead_of_mixing_scoring_semantics():
    series = (
        snapshot(30, (obs("a30", "routine-30", loss=4),), rulepack_digest=sha("rules-A")),
        snapshot(31, (obs("a31", "routine-31", loss=3),), rulepack_digest=sha("rules-A")),
        snapshot(32, (obs("a32", "routine-32", loss=2),), rulepack_digest=sha("rules-B")),
    )
    trend = build_category_trends(series)[0]
    assert trend.direction is TrendDirection.NOT_COMPARABLE
    assert trend.rulepack_changed is True
    assert "rulepack-changed" in trend.comparability_reasons
    assert trend.delta_units is None


def test_model_and_composition_changes_are_visible_caveats_not_hidden():
    series = (
        snapshot(40, (obs("a40", "routine-40", loss=4),), composition="comp-A", model_digest=sha("model-A")),
        snapshot(41, (obs("a41", "routine-41", loss=3),), composition="comp-A", model_digest=sha("model-A")),
        snapshot(42, (obs("a42", "routine-42", loss=2),), composition="comp-B", model_digest=sha("model-B")),
        snapshot(43, (obs("a43", "routine-43", loss=1),), composition="comp-B", model_digest=sha("model-B")),
    )
    trend = build_category_trends(series)[0]
    assert trend.direction is TrendDirection.IMPROVING
    assert trend.composition_changed is True
    assert trend.model_bundle_changed is True
    assert "composition-changed" in trend.comparability_reasons
    assert "model-bundle-changed" in trend.comparability_reasons


def test_less_than_policy_minimum_is_insufficient_not_a_direction_claim():
    series = (
        snapshot(50, (obs("a50", "routine-50", loss=4),)),
        snapshot(51, (obs("a51", "routine-51", loss=1),)),
    )
    trend = build_category_trends(series, policy=TrendPolicy(minimum_points=3))[0]
    assert trend.direction is TrendDirection.INSUFFICIENT_DATA
    assert trend.delta_units is None
    assert "insufficient-points:2<3" in trend.comparability_reasons


def test_unreviewed_observation_cannot_enter_snapshot_or_longitudinal_truth():
    with pytest.raises(PerformanceAnalysisError, match="only contain accepted observations"):
        snapshot(
            60,
            (obs("p60", "routine-60", state=ObservationReviewState.PROPOSED),),
        )


def test_cross_athlete_and_cross_apparatus_series_are_rejected():
    one = snapshot(70, (obs("a70", "routine-70"),))
    other_athlete = snapshot(
        71,
        (obs("a71", "routine-71", athlete="athlete-2"),),
        athlete="athlete-2",
    )
    with pytest.raises(PerformanceAnalysisError, match="different athletes"):
        build_category_trends((one, other_athlete))

    other_apparatus = RoutinePerformanceSnapshot(
        **{
            **snapshot(72, (obs("a72", "routine-72"),)).__dict__,
            "apparatus": Apparatus.FX,
            "observations": tuple(
                PerformanceObservation(
                    **{**item.__dict__, "apparatus": Apparatus.FX}
                )
                for item in snapshot(72, (obs("a72", "routine-72"),)).observations
            ),
        }
    )
    with pytest.raises(PerformanceAnalysisError, match="one apparatus"):
        build_category_trends((one, other_apparatus))


def test_multiple_analysis_revisions_of_same_routine_require_explicit_selection():
    first = snapshot(
        80,
        (obs("a80", "routine-same", loss=3),),
        routine_id="routine-same",
        revision_id="revision-old",
    )
    second = snapshot(
        81,
        (obs("a81", "routine-same", loss=2),),
        routine_id="routine-same",
        revision_id="revision-new",
    )
    with pytest.raises(PerformanceAnalysisError, match="cannot silently choose"):
        build_category_trends((first, second))


def test_longitudinal_report_is_pseudonymous_and_hash_bound_to_selected_snapshots():
    series = tuple(
        snapshot(index + 90, (obs(f"a{index}", f"routine-{index + 90}", loss=4 - index),))
        for index in range(3)
    )
    report = build_longitudinal_report(
        report_id="long-report-1",
        generated_at=T0 + timedelta(days=100),
        snapshots=series,
    )
    payload = report.normalized_dict()
    assert payload["athlete_group_id"] == "athlete-1"
    assert "athlete_name" not in payload
    assert payload["snapshot_digests"] == [item.digest for item in series]
    assert len(report.digest) == 64
