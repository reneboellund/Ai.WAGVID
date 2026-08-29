import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.floor_exercise import (
    FloorCapabilityState,
    FloorEvidenceRef,
    FloorExerciseBundle,
    FloorGeometryCapability,
    RoutineTiming,
    TimingSource,
)
from ai_wagvid.floor_exercise_exports import floor_exercise_payload

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "floor-exercise-analysis-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 20, 0, tzinfo=UTC)


def payload() -> dict:
    evidence = FloorEvidenceRef("e1", "1" * 64, 900, 9100, "camera-corner")
    routine_timing = RoutineTiming(
        start_ms=1000,
        end_ms=9000,
        source=TimingSource.AUDIO_TIMELINE,
        timeline_digest="2" * 64,
        confidence_milli=850,
        evidence=(evidence,),
    )
    bundle = FloorExerciseBundle(
        analysis_id="fx-1",
        routine_id="routine-1",
        source_media_sha256="3" * 64,
        timing=routine_timing,
        geometry=FloorGeometryCapability(FloorCapabilityState.UNAVAILABLE, None, "floor polygon not calibrated"),
        intervals=(),
        observations=(),
        connections=(),
        model_bundle_digest="4" * 64,
        perception_bundle_digest="5" * 64,
        created_at=T0,
    )
    return floor_exercise_payload(bundle)


def test_serializer_validates_against_public_schema():
    assert list(VALIDATOR.iter_errors(payload())) == []


def test_public_schema_rejects_music_semantics():
    value = payload()
    value["timing"]["music_style"] = "fixture-style"
    value["timing"]["artist"] = "fixture-artist"
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_public_schema_rejects_score_and_official_result():
    value = payload()
    value["d_score"] = 5.4
    value["official_result"] = {"final": 13.0}
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_public_schema_rejects_connection_value():
    value = payload()
    value["connections"] = [{
        "connection_id": "c1",
        "first_interval_id": "i1",
        "second_interval_id": "i2",
        "gap_ms": 30,
        "evidence_observation_ids": ["o1"],
        "state": "continuous",
        "confidence_milli": 800,
        "connection_value": 0.2
    }]
    errors = list(VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)
