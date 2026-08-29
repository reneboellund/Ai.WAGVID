from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.temporal_recognition import (
    CandidateProbabilityMass,
    DistinguishingObservation,
    ElementAlternative,
    MultiViewIntervalRef,
    ResolutionPolicy,
    ResolutionState,
    TemporalElementCandidate,
    TemporalRecognitionBundle,
    TemporalRecognitionError,
    accept_human_element_decision,
    resolve_candidate,
)

T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def observation(observation_id: str = "obs-1") -> DistinguishingObservation:
    return DistinguishingObservation(
        observation_id=observation_id,
        evidence_digest="1" * 64,
        attribute="body-shape",
        value="fixture-shape",
        confidence_milli=900,
    )


def view(camera: str = "cam-1", seed: str = "2", start: int = 900, end: int = 2100):
    return MultiViewIntervalRef(
        media_sha256=seed * 64,
        camera_id=camera,
        start_ms=start,
        end_ms=end,
        evidence_digest="3" * 64,
    )


def alternative(element: str, family: str, probability: int, observations=("obs-1",)):
    return ElementAlternative(
        element_id=element,
        family=family,
        probability_milli=probability,
        distinguishing_observation_ids=tuple(observations),
    )


def candidate(
    *,
    alternatives=None,
    unknown=100,
    other_known=100,
    start=1000,
    end=2000,
    segment_id="segment-1",
    views=None,
):
    alternatives = alternatives or (
        alternative("BB.family.a", "family-a", 500),
        alternative("BB.family.b", "family-a", 300),
    )
    return TemporalElementCandidate(
        segment_id=segment_id,
        routine_id="routine-1",
        apparatus=Apparatus.BB,
        start_ms=start,
        end_ms=end,
        views=tuple(views or (view(),)),
        observations=(observation(),),
        probability=CandidateProbabilityMass(
            alternatives=tuple(alternatives),
            unknown_ood_milli=unknown,
            other_known_milli=other_known,
        ),
        model_bundle_digest="4" * 64,
        model_config_digest="5" * 64,
        perception_bundle_digest="6" * 64,
        sequence_context_digest="7" * 64,
        created_at=T0,
    )


def test_probability_mass_must_sum_to_exactly_1000():
    with pytest.raises(TemporalRecognitionError, match="sum to 1000"):
        CandidateProbabilityMass(
            alternatives=(alternative("a", "family", 800),),
            unknown_ood_milli=100,
            other_known_milli=50,
        )


def test_ranked_alternatives_must_be_deterministically_sorted():
    with pytest.raises(TemporalRecognitionError, match="deterministic probability ranking"):
        CandidateProbabilityMass(
            alternatives=(
                alternative("low", "family", 300),
                alternative("high", "family", 500),
            ),
            unknown_ood_milli=100,
            other_known_milli=100,
        )


def test_high_unknown_ood_probability_resolves_to_unknown_without_family_or_element():
    item = candidate(
        alternatives=(
            alternative("BB.a", "family-a", 250),
            alternative("BB.b", "family-b", 150),
        ),
        unknown=500,
        other_known=100,
    )
    result = resolve_candidate(item)
    assert result.state is ResolutionState.UNKNOWN
    assert result.family is None
    assert result.element_id is None
    assert result.reason == "unknown-ood-threshold"


def test_same_family_mass_can_resolve_family_while_exact_identity_remains_unresolved():
    item = candidate(
        alternatives=(
            alternative("BB.a", "family-a", 500),
            alternative("BB.b", "family-a", 300),
        ),
        unknown=100,
        other_known=100,
    )
    result = resolve_candidate(item)
    assert result.state is ResolutionState.FAMILY_ONLY
    assert result.family == "family-a"
    assert result.element_id is None


def test_default_policy_does_not_auto_accept_exact_identity_even_with_high_top1():
    item = candidate(
        alternatives=(
            alternative("BB.a", "family-a", 850),
            alternative("BB.b", "family-b", 50),
        ),
        unknown=50,
        other_known=50,
    )
    result = resolve_candidate(item)
    assert result.state is not ResolutionState.EXACT_ACCEPTED

    explicit = resolve_candidate(
        item,
        policy=ResolutionPolicy(
            automatic_exact_accept=True,
            exact_top_at_least_milli=800,
            exact_margin_at_least_milli=200,
        ),
    )
    assert explicit.state is ResolutionState.EXACT_ACCEPTED
    assert explicit.element_id == "BB.a"
    assert explicit.reason == "explicit-auto-exact-policy"


def test_human_can_override_ranked_list_without_forcing_model_to_have_predicted_truth():
    item = candidate()
    decision = accept_human_element_decision(
        item,
        decision_id="decision-1",
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        chosen_element_id="BB.corrected.by.human",
        chosen_family="family-c",
        reason_code="candidate-list-missed-correct-identity",
        notes="Evidence supports a different element than the ranked model alternatives",
        decided_at=T0 + timedelta(minutes=1),
    )
    assert decision.model_candidate_override is True
    assert decision.chosen_element_id == "BB.corrected.by.human"
    assert len(decision.digest) == 64


def test_human_family_only_decision_is_allowed_without_fake_exact_identity():
    item = candidate()
    decision = accept_human_element_decision(
        item,
        decision_id="decision-family",
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        chosen_element_id=None,
        chosen_family="family-a",
        reason_code="exact-element-unresolved",
        notes="Family is supported but exact code cannot be resolved from available views",
        decided_at=T0 + timedelta(minutes=1),
    )
    assert decision.chosen_family == "family-a"
    assert decision.chosen_element_id is None
    assert decision.model_candidate_override is False


def test_view_must_cover_canonical_candidate_interval():
    with pytest.raises(TemporalRecognitionError, match="cover the canonical candidate interval"):
        candidate(views=(view(start=1100, end=2100),))


def test_multi_camera_candidate_keeps_separate_media_and_camera_evidence_refs():
    item = candidate(
        views=(
            view(camera="cam-side", seed="2"),
            view(camera="cam-end", seed="8"),
        )
    )
    assert len(item.views) == 2
    assert {entry.camera_id for entry in item.views} == {"cam-side", "cam-end"}
    assert len({entry.media_sha256 for entry in item.views}) == 2


def test_candidate_alternative_cannot_reference_unknown_observation():
    with pytest.raises(TemporalRecognitionError, match="unknown observations"):
        candidate(
            alternatives=(
                alternative("BB.a", "family-a", 800, observations=("missing-observation",)),
            ),
            unknown=100,
            other_known=100,
        )


def test_recognition_bundle_is_chronological_nonoverlapping_and_one_provenance_set():
    first = candidate(segment_id="segment-1", start=1000, end=2000)
    second = candidate(
        segment_id="segment-2",
        start=2100,
        end=3000,
        views=(view(start=2000, end=3100),),
    )
    bundle = TemporalRecognitionBundle(
        bundle_id="bundle-1",
        routine_id="routine-1",
        apparatus=Apparatus.BB,
        candidates=(first, second),
        model_bundle_digest="4" * 64,
        perception_bundle_digest="6" * 64,
        created_at=T0 + timedelta(minutes=2),
    )
    assert len(bundle.digest) == 64

    overlapping = candidate(
        segment_id="segment-overlap",
        start=1900,
        end=2500,
        views=(view(start=1800, end=2600),),
    )
    with pytest.raises(TemporalRecognitionError, match="may not overlap"):
        TemporalRecognitionBundle(
            bundle_id="bundle-bad",
            routine_id="routine-1",
            apparatus=Apparatus.BB,
            candidates=(first, overlapping),
            model_bundle_digest="4" * 64,
            perception_bundle_digest="6" * 64,
            created_at=T0 + timedelta(minutes=2),
        )
