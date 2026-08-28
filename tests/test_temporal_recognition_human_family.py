from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.temporal_recognition import (
    CandidateProbabilityMass,
    DistinguishingObservation,
    ElementAlternative,
    MultiViewIntervalRef,
    TemporalElementCandidate,
    TemporalRecognitionError,
    accept_human_element_decision,
)

T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def candidate() -> TemporalElementCandidate:
    observation = DistinguishingObservation(
        observation_id="obs-1",
        evidence_digest="1" * 64,
        attribute="body-shape",
        value="fixture-shape",
        confidence_milli=900,
    )
    return TemporalElementCandidate(
        segment_id="segment-1",
        routine_id="routine-1",
        apparatus=Apparatus.BB,
        start_ms=1000,
        end_ms=2000,
        views=(
            MultiViewIntervalRef(
                media_sha256="2" * 64,
                camera_id="cam-side",
                start_ms=900,
                end_ms=2100,
                evidence_digest="3" * 64,
            ),
        ),
        observations=(observation,),
        probability=CandidateProbabilityMass(
            alternatives=(
                ElementAlternative(
                    element_id="BB.a",
                    family="family-a",
                    probability_milli=600,
                    distinguishing_observation_ids=("obs-1",),
                ),
                ElementAlternative(
                    element_id="BB.b",
                    family="family-b",
                    probability_milli=200,
                    distinguishing_observation_ids=("obs-1",),
                ),
            ),
            unknown_ood_milli=100,
            other_known_milli=100,
        ),
        model_bundle_digest="4" * 64,
        model_config_digest="5" * 64,
        perception_bundle_digest="6" * 64,
        sequence_context_digest="7" * 64,
        created_at=T0,
    )


def test_ranked_element_requires_its_ranked_family():
    item = candidate()
    with pytest.raises(TemporalRecognitionError, match="family must match"):
        accept_human_element_decision(
            item,
            decision_id="decision-wrong-family",
            reviewer_id="reviewer-1",
            reviewer_qualification_ref="qualified-reviewer:wags",
            chosen_element_id="BB.a",
            chosen_family="family-b",
            reason_code="human-review",
            notes="This intentionally mismatches the ranked candidate family",
            decided_at=T0 + timedelta(minutes=1),
        )


def test_ranked_element_with_matching_family_is_not_model_override():
    item = candidate()
    decision = accept_human_element_decision(
        item,
        decision_id="decision-ranked",
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        chosen_element_id="BB.a",
        chosen_family="family-a",
        reason_code="human-confirmed-ranked-candidate",
        notes="Evidence supports the ranked candidate and its family",
        decided_at=T0 + timedelta(minutes=1),
    )
    assert decision.model_candidate_override is False


def test_out_of_top_k_exact_element_remains_explicit_model_override():
    item = candidate()
    decision = accept_human_element_decision(
        item,
        decision_id="decision-override",
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        chosen_element_id="BB.corrected.by.human",
        chosen_family="family-c",
        reason_code="candidate-list-missed-correct-identity",
        notes="Evidence supports a different element than the ranked model alternatives",
        decided_at=T0 + timedelta(minutes=1),
    )
    assert decision.model_candidate_override is True
    assert decision.chosen_family == "family-c"
