from datetime import UTC, datetime

import pytest

from ai_wagvid.balance_beam import (
    ArtistryCriterionDecision,
    BalanceBeamBundle,
    BalanceBeamError,
    BeamCapabilityState,
    BeamElementRef,
    BeamEvidenceRef,
    BeamGeometryCapability,
    BeamObservation,
    BeamObservationKind,
    BeamSeriesCandidate,
    SeriesState,
)

T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
GEOMETRY = "4" * 64


def evidence(start=0, end=1000):
    return BeamEvidenceRef("e1", "1" * 64, start, end, "camera-side")


def test_alignment_requires_beam_geometry():
    with pytest.raises(BalanceBeamError, match="requires geometry"):
        BeamObservation(
            observation_id="alignment-1",
            kind=BeamObservationKind.ALIGNMENT,
            start_ms=100,
            end_ms=200,
            value="foot-offset-candidate",
            confidence_milli=800,
            evidence=(evidence(90, 210),),
        )


def test_artistry_observation_requires_named_criterion():
    with pytest.raises(BalanceBeamError, match="criterion_id"):
        BeamObservation(
            observation_id="artistry-1",
            kind=BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE,
            start_ms=100,
            end_ms=200,
            value="observable-criterion-evidence",
            confidence_milli=600,
            evidence=(evidence(90, 210),),
        )


def test_non_artistry_observation_cannot_carry_artistry_criterion():
    with pytest.raises(BalanceBeamError, match="reserved"):
        BeamObservation(
            observation_id="pause-1",
            kind=BeamObservationKind.PAUSE_OR_HESITATION,
            start_ms=100,
            end_ms=200,
            value="pause-duration-observed",
            confidence_milli=800,
            evidence=(evidence(90, 210),),
            criterion_id="criterion-x",
        )


def test_unaccepted_element_cannot_claim_exact_identity():
    with pytest.raises(BalanceBeamError, match="unaccepted"):
        BeamElementRef("s1", "2" * 64, 100, 200, "family", "BB.fixture", False)


def test_series_requires_continuity_observation_evidence():
    with pytest.raises(BalanceBeamError, match="requires continuity evidence"):
        BeamSeriesCandidate(
            series_id="series-1",
            segment_ids=("s1", "s2"),
            state=SeriesState.UNRESOLVED,
            gap_ms=(20,),
            evidence_observation_ids=(),
            confidence_milli=500,
        )


def test_unavailable_geometry_rejects_geometry_bound_observation():
    alignment = BeamObservation(
        observation_id="alignment-1",
        kind=BeamObservationKind.ALIGNMENT,
        start_ms=100,
        end_ms=200,
        value="foot-offset-candidate",
        confidence_milli=800,
        evidence=(evidence(90, 210),),
        geometry_digest=GEOMETRY,
    )
    with pytest.raises(BalanceBeamError, match="unavailable beam geometry"):
        BalanceBeamBundle(
            analysis_id="bb-1",
            routine_id="routine-1",
            source_media_sha256="3" * 64,
            geometry=BeamGeometryCapability(BeamCapabilityState.UNAVAILABLE, None, "beam axis unavailable"),
            observations=(alignment,),
            elements=(),
            series=(),
            artistry_decisions=(),
            model_bundle_digest="5" * 64,
            perception_bundle_digest="6" * 64,
            created_at=T0,
        )


def test_artistry_decision_must_reference_matching_artistry_criterion_evidence():
    artistry = BeamObservation(
        observation_id="artistry-1",
        kind=BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE,
        start_ms=100,
        end_ms=200,
        value="criterion-evidence",
        confidence_milli=600,
        evidence=(evidence(90, 210),),
        criterion_id="criterion-a",
    )
    decision = ArtistryCriterionDecision(
        decision_id="decision-1",
        criterion_id="criterion-b",
        observation_digests=(artistry.digest,),
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        accepted=True,
        reason_code="criterion-review",
        notes="Reviewer decision for fixture",
        decided_at=T0,
    )
    with pytest.raises(BalanceBeamError, match="match criterion_id"):
        BalanceBeamBundle(
            analysis_id="bb-1",
            routine_id="routine-1",
            source_media_sha256="3" * 64,
            geometry=BeamGeometryCapability(BeamCapabilityState.UNAVAILABLE, None, "not needed for fixture"),
            observations=(artistry,),
            elements=(),
            series=(),
            artistry_decisions=(decision,),
            model_bundle_digest="5" * 64,
            perception_bundle_digest="6" * 64,
            created_at=T0,
        )


def test_valid_artistry_decision_stays_separate_from_score():
    artistry = BeamObservation(
        observation_id="artistry-1",
        kind=BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE,
        start_ms=100,
        end_ms=200,
        value="criterion-evidence",
        confidence_milli=600,
        evidence=(evidence(90, 210),),
        criterion_id="criterion-a",
    )
    decision = ArtistryCriterionDecision(
        decision_id="decision-1",
        criterion_id="criterion-a",
        observation_digests=(artistry.digest,),
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        accepted=True,
        reason_code="criterion-review",
        notes="Evidence supports the criterion interpretation",
        decided_at=T0,
    )
    bundle = BalanceBeamBundle(
        analysis_id="bb-1",
        routine_id="routine-1",
        source_media_sha256="3" * 64,
        geometry=BeamGeometryCapability(BeamCapabilityState.UNAVAILABLE, None, "geometry not required for artistry fixture"),
        observations=(artistry,),
        elements=(),
        series=(),
        artistry_decisions=(decision,),
        model_bundle_digest="5" * 64,
        perception_bundle_digest="6" * 64,
        created_at=T0,
    )
    assert bundle.apparatus.value == "BB"
    assert not hasattr(bundle, "artistry_score")
    assert not hasattr(bundle, "d_score")
