import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.uneven_bars import (
    BarIdentity,
    TopologyEventKind,
    UBContinuityCandidate,
    UBElementCandidateRef,
    UBReferenceEvidence,
    UBTopologyEvent,
    UnevenBarsTopologyBundle,
)
from ai_wagvid.uneven_bars_exports import uneven_bars_payload

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "uneven-bars-topology-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
GEOMETRY = "4" * 64


def payload() -> dict:
    evidence = UBReferenceEvidence("e1", "1" * 64, 100, 300, "camera-side")
    release = UBTopologyEvent(
        event_id="release-1",
        kind=TopologyEventKind.RELEASE,
        at_ms=190,
        from_bar=BarIdentity.HIGH,
        to_bar=BarIdentity.UNKNOWN,
        confidence_milli=800,
        evidence=(evidence,),
        geometry_digest=GEOMETRY,
    )
    regrasp = UBTopologyEvent(
        event_id="regrasp-1",
        kind=TopologyEventKind.REGRASP,
        at_ms=230,
        from_bar=BarIdentity.UNKNOWN,
        to_bar=BarIdentity.HIGH,
        confidence_milli=800,
        evidence=(evidence,),
        geometry_digest=GEOMETRY,
    )
    elements = (
        UBElementCandidateRef("s1", "2" * 64, 120, 190, "family-a", "UB.a", True),
        UBElementCandidateRef("s2", "3" * 64, 230, 300, "family-b", "UB.b", True),
    )
    continuity = UBContinuityCandidate(
        "continuity-1", "s1", "s2", 40, ("release-1", "regrasp-1"), "continuous", 800
    )
    bundle = UnevenBarsTopologyBundle(
        analysis_id="ub-1",
        routine_id="routine-1",
        source_media_sha256="5" * 64,
        contacts=(),
        events=(release, regrasp),
        elements=elements,
        continuity=(continuity,),
        geometry_digest=GEOMETRY,
        model_bundle_digest="6" * 64,
        perception_bundle_digest="7" * 64,
        created_at=T0,
    )
    return uneven_bars_payload(bundle)


def test_serializer_validates_against_public_schema():
    assert list(VALIDATOR.iter_errors(payload())) == []


def test_public_schema_rejects_connection_value_and_score_fields():
    value = payload()
    value["continuity"][0]["connection_value"] = 0.2
    value["d_score"] = 5.6
    errors = list(VALIDATOR.iter_errors(value))
    assert len(errors) >= 2
    assert all("Additional properties are not allowed" in error.message for error in errors)


def test_public_schema_rejects_official_result():
    value = payload()
    value["official_result"] = {"d": 5.6}
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)
