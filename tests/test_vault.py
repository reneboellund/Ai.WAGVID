from datetime import UTC, datetime

import pytest

from ai_wagvid.vault import (
    CapabilityState,
    VaultAnalysisBundle,
    VaultAnalysisError,
    VaultEvidenceRef,
    VaultGeometryCapability,
    VaultIdentityAlternative,
    VaultIdentityCandidates,
    VaultObservation,
    VaultObservationKind,
    VaultPhase,
    VaultPhaseInterval,
    validate_required_phase_order,
)


T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def evidence(evidence_id: str, start: int, end: int) -> VaultEvidenceRef:
    return VaultEvidenceRef(
        evidence_id=evidence_id,
        evidence_digest=("a" if evidence_id == "e1" else "b") * 64,
        start_ms=start,
        end_ms=end,
        camera_id="camera-side",
    )


def phase(kind: VaultPhase, start: int, end: int) -> VaultPhaseInterval:
    return VaultPhaseInterval(
        phase=kind,
        start_ms=start,
        end_ms=end,
        confidence_milli=900,
        evidence=(evidence("e1", max(0, start - 10), end + 10),),
    )


def identity(*observation_ids: str) -> VaultIdentityCandidates:
    return VaultIdentityCandidates(
        alternatives=(
            VaultIdentityAlternative(
                element_id="VT.fixture-a",
                family="fixture-family",
                probability_milli=600,
                evidence_observation_ids=tuple(observation_ids),
            ),
        ),
        unknown_ood_milli=250,
        other_known_milli=150,
    )


def base_bundle(*, observations=(), capability=None) -> VaultAnalysisBundle:
    phases = (
        phase(VaultPhase.SPRINGBOARD_CONTACT, 100, 150),
        phase(VaultPhase.PRE_FLIGHT, 150, 250),
        phase(VaultPhase.TABLE_SUPPORT, 250, 300),
        phase(VaultPhase.REPULSION, 300, 320),
        phase(VaultPhase.POST_FLIGHT, 320, 600),
        phase(VaultPhase.LANDING, 600, 650),
    )
    return VaultAnalysisBundle(
        analysis_id="vault-analysis-1",
        routine_id="routine-1",
        source_media_sha256="1" * 64,
        phases=phases,
        observations=tuple(observations),
        identity=identity(*(item.observation_id for item in observations)),
        corridor_boundary_capability=capability
        or VaultGeometryCapability(
            state=CapabilityState.UNAVAILABLE,
            calibration_digest=None,
            reason="landing corridor not calibrated",
        ),
        model_bundle_digest="2" * 64,
        perception_bundle_digest="3" * 64,
        created_at=T0,
        limitations=("approach-not-observed",),
    )


def test_vault_bundle_is_pre_scoring_and_fixed_to_vt():
    bundle = base_bundle()
    assert bundle.apparatus.value == "VT"
    assert len(bundle.digest) == 64
    assert not hasattr(bundle, "d_score")
    assert not hasattr(bundle, "final_score")


def test_phase_evidence_must_cover_canonical_phase_interval():
    with pytest.raises(VaultAnalysisError, match="cover"):
        VaultPhaseInterval(
            phase=VaultPhase.LANDING,
            start_ms=600,
            end_ms=650,
            confidence_milli=800,
            evidence=(evidence("e1", 610, 640),),
        )


def test_semantic_phase_order_is_validated_separately_from_timestamps():
    reversed_semantics = (
        phase(VaultPhase.POST_FLIGHT, 100, 200),
        phase(VaultPhase.TABLE_SUPPORT, 200, 250),
    )
    with pytest.raises(VaultAnalysisError, match="semantic order"):
        validate_required_phase_order(reversed_semantics)


def test_identity_probability_mass_is_explicit_and_complete():
    with pytest.raises(VaultAnalysisError, match="total 1000"):
        VaultIdentityCandidates(
            alternatives=(
                VaultIdentityAlternative(
                    element_id="VT.fixture",
                    family="fixture-family",
                    probability_milli=600,
                    evidence_observation_ids=(),
                ),
            ),
            unknown_ood_milli=100,
            other_known_milli=100,
        )


def test_identity_cannot_reference_missing_observation():
    with pytest.raises(VaultAnalysisError, match="unknown observations"):
        VaultAnalysisBundle(
            analysis_id="vault-analysis-2",
            routine_id="routine-2",
            source_media_sha256="1" * 64,
            phases=(phase(VaultPhase.LANDING, 600, 650),),
            observations=(),
            identity=identity("missing-observation"),
            corridor_boundary_capability=VaultGeometryCapability(
                state=CapabilityState.UNAVAILABLE,
                calibration_digest=None,
                reason="not calibrated",
            ),
            model_bundle_digest="2" * 64,
            perception_bundle_digest="3" * 64,
            created_at=T0,
        )


def test_corridor_boundary_observation_requires_calibration():
    with pytest.raises(VaultAnalysisError, match="requires calibration"):
        VaultObservation(
            observation_id="boundary-1",
            kind=VaultObservationKind.CORRIDOR_OR_BOUNDARY,
            phase=VaultPhase.LANDING,
            value="candidate-foot-outside-corridor",
            confidence_milli=700,
            evidence=(evidence("e1", 600, 650),),
            calibration_digest=None,
        )


def test_unavailable_boundary_capability_cannot_emit_boundary_observation():
    boundary = VaultObservation(
        observation_id="boundary-1",
        kind=VaultObservationKind.CORRIDOR_OR_BOUNDARY,
        phase=VaultPhase.LANDING,
        value="candidate-foot-outside-corridor",
        confidence_milli=700,
        evidence=(evidence("e1", 600, 650),),
        calibration_digest="4" * 64,
    )
    with pytest.raises(VaultAnalysisError, match="cannot emit boundary"):
        base_bundle(observations=(boundary,))


def test_available_boundary_capability_accepts_calibration_bound_observation():
    calibration = "4" * 64
    boundary = VaultObservation(
        observation_id="boundary-1",
        kind=VaultObservationKind.CORRIDOR_OR_BOUNDARY,
        phase=VaultPhase.LANDING,
        value="candidate-foot-outside-corridor",
        confidence_milli=700,
        evidence=(evidence("e1", 600, 650),),
        calibration_digest=calibration,
    )
    bundle = base_bundle(
        observations=(boundary,),
        capability=VaultGeometryCapability(
            state=CapabilityState.AVAILABLE,
            calibration_digest=calibration,
            reason="landing corridor calibration verified",
        ),
    )
    assert bundle.corridor_boundary_capability.state is CapabilityState.AVAILABLE


def test_non_geometry_observation_can_exist_without_calibration():
    landing = VaultObservation(
        observation_id="landing-1",
        kind=VaultObservationKind.LANDING_DISPLACEMENT,
        phase=VaultPhase.LANDING,
        value="visible-step-candidate",
        confidence_milli=650,
        evidence=(evidence("e1", 600, 650),),
        calibration_digest=None,
    )
    bundle = base_bundle(observations=(landing,))
    assert bundle.observations[0].kind is VaultObservationKind.LANDING_DISPLACEMENT
