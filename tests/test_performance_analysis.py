import hashlib
from datetime import UTC, datetime

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.performance_analysis import (
    CoachPriorityInput,
    CoachingHypothesis,
    CoachingHypothesisState,
    ObservationPolarity,
    ObservationReviewState,
    PerformanceAnalysisError,
    PerformanceEvidenceRef,
    PerformanceObservation,
    PriorityPolicy,
    TrainingFocusState,
    TrainingFocusSuggestion,
    build_patterns,
    build_performance_report,
    rank_priorities,
)


T0 = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)


def observation(
    observation_id: str,
    routine_id: str,
    *,
    pattern_key: str = "landing-control",
    category: str = "landing",
    polarity: ObservationPolarity = ObservationPolarity.POINT_LOSS,
    point_loss_units: int | None = 2,
    confidence: int = 900,
    state: ObservationReviewState = ObservationReviewState.ACCEPTED,
) -> PerformanceObservation:
    evidence_digest = hashlib.sha256(f"evidence:{observation_id}".encode()).hexdigest()
    return PerformanceObservation(
        observation_id=observation_id,
        athlete_group_id="athlete-pseudo-1",
        routine_id=routine_id,
        event_group_id=f"event-{routine_id}",
        apparatus=Apparatus.BB,
        category=category,
        pattern_key=pattern_key,
        phase="landing",
        element_family="fixture-family",
        polarity=polarity,
        description="Evidence-backed fixture observation",
        evidence=(PerformanceEvidenceRef(f"ev-{observation_id}", evidence_digest),),
        confidence_milli=confidence,
        review_state=state,
        source_digest="f" * 64,
        point_loss_units=point_loss_units,
    )


def test_pattern_builder_refuses_unreviewed_observations():
    with pytest.raises(PerformanceAnalysisError, match="only use accepted observations"):
        build_patterns(
            (
                observation("a1", "r1", state=ObservationReviewState.PROPOSED),
                observation("a2", "r2"),
            )
        )


def test_recurring_pattern_aggregates_routines_loss_evidence_and_conservative_confidence():
    observations = (
        observation("a1", "r1", point_loss_units=2, confidence=920),
        observation("a2", "r2", point_loss_units=3, confidence=810),
        observation("a3", "r2", point_loss_units=1, confidence=870),
    )
    patterns = build_patterns(observations, minimum_occurrences=2)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.pattern_key == "landing-control"
    assert pattern.occurrence_count == 3
    assert pattern.routine_count == 2
    assert pattern.point_loss_units == 6
    assert pattern.confidence_floor_milli == 810
    assert pattern.evidence_count == 3


def test_single_observation_does_not_become_a_recurring_pattern_by_default():
    assert build_patterns((observation("a1", "r1"),), minimum_occurrences=2) == ()


def test_strength_and_point_loss_with_same_category_are_not_collapsed_into_one_pattern():
    strength = observation(
        "s1",
        "r1",
        pattern_key="landing-control",
        polarity=ObservationPolarity.STRENGTH,
        point_loss_units=None,
    )
    strength2 = observation(
        "s2",
        "r2",
        pattern_key="landing-control",
        polarity=ObservationPolarity.STRENGTH,
        point_loss_units=None,
    )
    loss = observation("l1", "r1")
    loss2 = observation("l2", "r2")
    patterns = build_patterns((strength, strength2, loss, loss2))
    assert {item.polarity for item in patterns} == {
        ObservationPolarity.STRENGTH,
        ObservationPolarity.POINT_LOSS,
    }


def test_point_loss_priority_requires_explicit_coach_actionability_input():
    pattern = build_patterns((observation("a1", "r1"), observation("a2", "r2")))[0]
    with pytest.raises(PerformanceAnalysisError, match="requires coach priority input"):
        rank_priorities((pattern,), ())


def test_priority_order_is_transparent_lexicographic_not_hidden_ai_score():
    high_loss = build_patterns(
        (
            observation("a1", "r1", pattern_key="pattern-a", point_loss_units=4),
            observation("a2", "r2", pattern_key="pattern-a", point_loss_units=4),
        )
    )[0]
    recurrent = build_patterns(
        (
            observation("b1", "r1", pattern_key="pattern-b", point_loss_units=2),
            observation("b2", "r2", pattern_key="pattern-b", point_loss_units=2),
            observation("b3", "r3", pattern_key="pattern-b", point_loss_units=2),
        )
    )[0]
    inputs = (
        CoachPriorityInput(high_loss.digest, "coach-1", 500, 500, "Coach review A"),
        CoachPriorityInput(recurrent.digest, "coach-1", 900, 900, "Coach review B"),
    )

    loss_first = rank_priorities((recurrent, high_loss), inputs)
    assert loss_first[0].pattern_key == "pattern-a"
    assert loss_first[0].dimensions[0] == ("point_loss_units", 8)

    recurrence_first = rank_priorities(
        (recurrent, high_loss),
        inputs,
        policy=PriorityPolicy(
            ("routine_count", "occurrence_count", "point_loss_units", "actionability_milli")
        ),
    )
    assert recurrence_first[0].pattern_key == "pattern-b"
    assert recurrence_first[0].dimensions[0] == ("routine_count", 3)


def test_actionability_is_not_inferred_from_model_confidence():
    pattern = build_patterns(
        (observation("a1", "r1", confidence=1000), observation("a2", "r2", confidence=1000))
    )[0]
    coach = CoachPriorityInput(
        pattern_digest=pattern.digest,
        coach_id="coach-1",
        technical_importance_milli=200,
        actionability_milli=150,
        rationale="Coach considers this lower actionability despite high observation confidence",
    )
    priority = rank_priorities((pattern,), (coach,))[0]
    dimensions = dict(priority.dimensions)
    assert dimensions["confidence_floor_milli"] == 1000
    assert dimensions["actionability_milli"] == 150
    assert priority.coach_id == "coach-1"


def test_report_serialization_keeps_facts_patterns_hypotheses_and_training_focus_separate():
    strength = observation(
        "s1",
        "r1",
        pattern_key="stable-strength",
        category="control",
        polarity=ObservationPolarity.STRENGTH,
        point_loss_units=None,
    )
    strength2 = observation(
        "s2",
        "r2",
        pattern_key="stable-strength",
        category="control",
        polarity=ObservationPolarity.STRENGTH,
        point_loss_units=None,
    )
    loss1 = observation("l1", "r1")
    loss2 = observation("l2", "r2")
    observations = (strength, strength2, loss1, loss2)
    patterns = build_patterns(observations)
    loss_pattern = next(item for item in patterns if item.polarity is ObservationPolarity.POINT_LOSS)
    priorities = rank_priorities(
        patterns,
        (
            CoachPriorityInput(
                loss_pattern.digest,
                "coach-1",
                800,
                700,
                "Coach-set development priority",
            ),
        ),
    )
    hypothesis = CoachingHypothesis(
        hypothesis_id="hyp-1",
        pattern_digest=loss_pattern.digest,
        text="Coach should investigate the underlying landing-mechanics cause",
        created_by="analysis-assistant",
        created_at=T0,
    )
    focus = TrainingFocusSuggestion(
        focus_id="focus-1",
        pattern_digest=loss_pattern.digest,
        text="Review landing mechanics and select an appropriate drill",
        created_by="analysis-assistant",
        created_at=T0,
    )
    report = build_performance_report(
        report_id="report-1",
        athlete_group_id="athlete-pseudo-1",
        generated_at=T0,
        observations=observations,
        patterns=patterns,
        priorities=priorities,
        coaching_hypotheses=(hypothesis,),
        training_focuses=(focus,),
    )
    payload = report.normalized_dict()
    assert len(payload["observed_facts"]["strengths"]) == 2
    assert len(payload["observed_facts"]["point_loss"]) == 2
    assert all(item["semantic_layer"] == "observed-fact" for item in payload["observed_facts"]["point_loss"])
    assert all(item["semantic_layer"] == "pattern" for item in payload["patterns"])
    assert payload["coaching_hypotheses"][0]["semantic_layer"] == "coaching-hypothesis"
    assert payload["suggested_training_focuses"][0]["semantic_layer"] == "suggested-training-focus"
    assert "athlete_name" not in payload


def test_coach_confirmation_is_explicit_state_not_rewriting_hypothesis_as_fact():
    pattern = build_patterns((observation("a1", "r1"), observation("a2", "r2")))[0]
    confirmed = CoachingHypothesis(
        hypothesis_id="hyp-1",
        pattern_digest=pattern.digest,
        text="Coach-confirmed technical hypothesis",
        created_by="analysis-assistant",
        created_at=T0,
        state=CoachingHypothesisState.COACH_CONFIRMED,
        coach_review_id="coach-review-1",
    )
    selected = TrainingFocusSuggestion(
        focus_id="focus-1",
        pattern_digest=pattern.digest,
        text="Coach-selected training focus",
        created_by="analysis-assistant",
        created_at=T0,
        state=TrainingFocusState.COACH_SELECTED,
        coach_review_id="coach-review-2",
    )
    assert confirmed.semantic_layer == "coaching-hypothesis"
    assert selected.semantic_layer == "suggested-training-focus"
