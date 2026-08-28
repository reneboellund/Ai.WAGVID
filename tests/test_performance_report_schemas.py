import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator

from ai_wagvid.domain import Apparatus
from ai_wagvid.longitudinal import RoutinePerformanceSnapshot, build_longitudinal_report
from ai_wagvid.performance_analysis import (
    CoachingHypothesis,
    CoachPriorityInput,
    ObservationPolarity,
    ObservationReviewState,
    PerformanceEvidenceRef,
    PerformanceObservation,
    TrainingFocusSuggestion,
    build_patterns,
    build_performance_report,
    rank_priorities,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
PERFORMANCE_SCHEMA = load_schema(ROOT / "schemas" / "performance-report-v1.schema.json")
LONGITUDINAL_SCHEMA = load_schema(ROOT / "schemas" / "longitudinal-report-v1.schema.json")
T0 = datetime(2026, 8, 17, 13, 30, tzinfo=UTC)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def observation(observation_id: str, routine_id: str, loss: int) -> PerformanceObservation:
    return PerformanceObservation(
        observation_id=observation_id,
        athlete_group_id="athlete-pseudo-1",
        routine_id=routine_id,
        event_group_id=f"event-{routine_id}",
        apparatus=Apparatus.BB,
        category="landing",
        pattern_key="landing-control",
        phase="landing",
        element_family="fixture-family",
        polarity=ObservationPolarity.POINT_LOSS,
        description="Reviewed fixture landing observation",
        evidence=(PerformanceEvidenceRef(f"ev-{observation_id}", sha(f"ev:{observation_id}")),),
        confidence_milli=900,
        review_state=ObservationReviewState.ACCEPTED,
        source_digest=sha(f"source:{observation_id}"),
        point_loss_units=loss,
    )


def test_performance_report_normalized_json_validates_against_public_schema():
    observations = (
        observation("o1", "routine-1", 3),
        observation("o2", "routine-2", 2),
    )
    patterns = build_patterns(observations)
    pattern = patterns[0]
    priorities = rank_priorities(
        patterns,
        (
            CoachPriorityInput(
                pattern_digest=pattern.digest,
                coach_id="coach-1",
                technical_importance_milli=800,
                actionability_milli=700,
                rationale="Coach-set priority fixture",
            ),
        ),
    )
    report = build_performance_report(
        report_id="performance-1",
        athlete_group_id="athlete-pseudo-1",
        generated_at=T0,
        observations=observations,
        patterns=patterns,
        priorities=priorities,
        coaching_hypotheses=(
            CoachingHypothesis(
                hypothesis_id="hyp-1",
                pattern_digest=pattern.digest,
                text="Coach should investigate the underlying cause",
                created_by="analysis-assistant",
                created_at=T0,
            ),
        ),
        training_focuses=(
            TrainingFocusSuggestion(
                focus_id="focus-1",
                pattern_digest=pattern.digest,
                text="Review landing mechanics",
                created_by="analysis-assistant",
                created_at=T0,
            ),
        ),
    )
    payload = json.loads(report.normalized_json())
    assert list(Draft202012Validator(PERFORMANCE_SCHEMA).iter_errors(payload)) == []


def test_longitudinal_report_normalized_json_validates_against_public_schema():
    snapshots = []
    for index, loss in enumerate((4, 3, 1)):
        routine_id = f"routine-{index + 1}"
        item = observation(f"long-{index}", routine_id, loss)
        snapshots.append(
            RoutinePerformanceSnapshot(
                snapshot_id=f"snapshot-{index}",
                athlete_group_id="athlete-pseudo-1",
                routine_id=routine_id,
                event_group_id=f"event-{index}",
                occurred_at=T0 + timedelta(days=index),
                apparatus=Apparatus.BB,
                analysis_revision_id=f"revision-{index}",
                analysis_revision_digest=sha(f"revision:{index}"),
                rulepack_id="fixture-rulepack@v1",
                rulepack_digest=sha("rulepack"),
                model_bundle_digest=sha("model"),
                composition_signature="composition-A",
                observations=(item,),
            )
        )
    report = build_longitudinal_report(
        report_id="longitudinal-1",
        generated_at=T0 + timedelta(days=10),
        snapshots=tuple(snapshots),
    )
    payload = json.loads(report.normalized_json())
    assert list(Draft202012Validator(LONGITUDINAL_SCHEMA).iter_errors(payload)) == []
    assert payload["trends"][0]["direction"] == "improving"
