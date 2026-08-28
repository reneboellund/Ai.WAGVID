import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.vault import (
    CapabilityState,
    VaultEvidenceRef,
    VaultGeometryCapability,
    VaultIdentityAlternative,
    VaultIdentityCandidates,
    VaultObservation,
    VaultObservationKind,
    VaultPhase,
    VaultPhaseInterval,
)
from ai_wagvid.vault_exports import vault_analysis_payload
from ai_wagvid.vault_factory import build_vault_analysis_bundle

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "vault-analysis-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def payload() -> dict:
    evidence = VaultEvidenceRef(
        evidence_id="e1",
        evidence_digest="1" * 64,
        start_ms=90,
        end_ms=710,
        camera_id="camera-side",
    )
    phases = (
        VaultPhaseInterval(VaultPhase.SPRINGBOARD_CONTACT, 100, 150, 900, (evidence,)),
        VaultPhaseInterval(VaultPhase.PRE_FLIGHT, 150, 250, 900, (evidence,)),
        VaultPhaseInterval(VaultPhase.TABLE_SUPPORT, 250, 300, 900, (evidence,)),
        VaultPhaseInterval(VaultPhase.REPULSION, 300, 320, 900, (evidence,)),
        VaultPhaseInterval(VaultPhase.POST_FLIGHT, 320, 600, 900, (evidence,)),
        VaultPhaseInterval(VaultPhase.LANDING, 600, 650, 900, (evidence,)),
    )
    landing = VaultObservation(
        observation_id="landing-1",
        kind=VaultObservationKind.LANDING_DISPLACEMENT,
        phase=VaultPhase.LANDING,
        value="visible-step-candidate",
        confidence_milli=700,
        evidence=(evidence,),
    )
    identity = VaultIdentityCandidates(
        alternatives=(VaultIdentityAlternative("VT.fixture", "fixture-family", 600, ("landing-1",)),),
        unknown_ood_milli=250,
        other_known_milli=150,
    )
    bundle = build_vault_analysis_bundle(
        analysis_id="vault-1",
        routine_id="routine-1",
        source_media_sha256="2" * 64,
        phases=phases,
        observations=(landing,),
        identity=identity,
        corridor_boundary_capability=VaultGeometryCapability(
            state=CapabilityState.UNAVAILABLE,
            calibration_digest=None,
            reason="corridor not calibrated",
        ),
        model_bundle_digest="3" * 64,
        perception_bundle_digest="4" * 64,
        created_at=T0,
    )
    return vault_analysis_payload(bundle)


def test_vault_serializer_validates_against_public_schema():
    assert list(VALIDATOR.iter_errors(payload())) == []


def test_vault_public_contract_rejects_score_fields():
    value = payload()
    value["d_score"] = 5.4
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_vault_public_contract_rejects_official_result_context():
    value = deepcopy(payload())
    value["official_result"] = {"final": 13.2}
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)
