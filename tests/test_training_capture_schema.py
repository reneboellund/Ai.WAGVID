import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]


def validator() -> Draft202012Validator:
    schema = json.loads(
        (ROOT / "schemas" / "training-capture-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def valid_capture() -> dict:
    return {
        "schema_version": "1.0.0",
        "capture_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "gymnast": {
            "gymnast_id": "gym-42",
            "name": "Test Gymnast",
            "level": "Trin 6",
            "license_number": "DK-12345",
        },
        "activity": {
            "kind": "drill",
            "apparatus": "balance-beam",
            "exercise_name": "Handstand",
            "coach_note": None,
            "recorded_at": "2026-08-16T10:00:00+02:00",
        },
        "device": {
            "device_id": "android-tripod-1",
            "platform": "android",
            "camera_facing": "back",
            "app_version": "0.1.0",
        },
        "control": {
            "mode": "motion-detection",
            "state": "recording",
            "remote_controlled": True,
            "motion_start_seconds": 0.8,
            "exercise_end_quiet_seconds": 4.0,
            "pre_roll_seconds": 2.0,
            "post_roll_seconds": 2.0,
            "recording_started_by": "motion-detector",
            "stop_reason": None,
        },
        "recording": {
            "storage_status": "pending",
            "video_uri": None,
            "sha256": None,
            "duration_ms": None,
        },
        "analysis": {
            "requested": True,
            "scope": "single-skill",
            "target_skill": "handstand",
            "status": "queued",
        },
    }


def test_training_capture_contract_is_valid() -> None:
    assert list(validator().iter_errors(valid_capture())) == []


def test_identity_and_level_are_required() -> None:
    capture = valid_capture()
    del capture["gymnast"]["license_number"]
    assert list(validator().iter_errors(capture))


def test_competition_is_not_a_training_activity_kind() -> None:
    capture = valid_capture()
    capture["activity"]["kind"] = "competition"
    assert list(validator().iter_errors(capture))
