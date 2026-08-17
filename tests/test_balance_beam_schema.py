import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.balance_beam import (
    BalanceBeamBundle,
    BeamCapabilityState,
    BeamEvidenceRef,
    BeamGeometryCapability,
    BeamObservation,
    BeamObservationKind,
)
from ai_wagvid.balance_beam_exports import balance_beam_payload


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "balance-beam-analysis-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def payload() -> dict:
    evidence = BeamEvidenceRef("e1", "1" * 64, 100, 200, "camera-side")
    artistry = BeamObservation(
        observation_id="artistry-1",
        kind=BeamObservationKind.ARTISTRY_CRITERION_EVIDENCE,
        start_ms=110,
        end_ms=190,
        value="criterion-evidence",
        confidence_milli=600,
        evidence=(evidence,),
        criterion_id="criterion-a",
    )
    bundle = BalanceBeamBundle(
        analysis_id="bb-1",
        routine_id="routine-1",
        source_media_sha256="2" * 64,
        geometry=BeamGeometryCapability(BeamCapabilityState.UNAVAILABLE, None, "not needed for fixture"),
        observations=(artistry,),
        elements=(),
        series=(),
        artistry_decisions=(),
        model_bundle_digest="3" * 64,
        perception_bundle_digest="4" * 64,
        created_at=T0,
    )
    return balance_beam_payload(bundle)


def test_serializer_validates_against_public_schema():
    assert list(VALIDATOR.iter_errors(payload())) == []


def test_public_schema_rejects_artistry_score():
    value = payload()
    value["artistry_score"] = 8.7
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_public_schema_rejects_d_score_and_official_result():
    value = payload()
    value["d_score"] = 5.2
    value["official_result"] = {"final": 13.1}
    errors = list(VALIDATOR.iter_errors(value))
    assert len(errors) >= 1
    assert any("Additional properties are not allowed" in error.message for error in errors)
