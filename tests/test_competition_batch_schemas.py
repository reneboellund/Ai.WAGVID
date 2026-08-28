from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.competition_batch import plan_competition_batch
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
EXCHANGE_SCHEMA = load_schema(ROOT / "schemas" / "competition-video-v1.schema.json")
TASK_SCHEMA = load_schema(ROOT / "schemas" / "competition-analysis-task-v1.schema.json")
T0 = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def record() -> dict:
    return {
        "schema": "ai.wagvid.competition-video.v1",
        "record_id": "record-1",
        "created_at": "2026-08-16T12:00:00+02:00",
        "competition": {
            "external_id": "competition-1",
            "name": "Fixture Competition",
            "start_date": "2026-08-16",
            "end_date": "2026-08-16",
            "timezone": "Europe/Copenhagen",
            "venue": "Fixture Hall",
            "city": "Fixture City",
            "organizer": "Fixture Organizer",
            "federation": "Fixture Federation",
            "rule_profile": "fixture-rule-profile",
        },
        "routine": {
            "external_id": "routine-1",
            "athlete_external_id": "athlete-1",
            "team_external_id": None,
            "apparatus": "BB",
            "round": "qualification",
            "rotation": 1,
            "start_order": 3,
            "competition_category": "fixture-category",
            "performed_at": "2026-08-16T10:15:00+02:00",
        },
        "media": [
            {
                "media_id": "media-1",
                "camera_id": "camera-1",
                "view": "side",
                "content_type": "video/mp4",
                "size_bytes": 123456,
                "duration_ms": 70000,
                "captured_at": "2026-08-16T10:14:00+02:00",
                "sha256": "c" * 64,
                "download_uri": "https://example.invalid/media/token",
            }
        ],
        "official_result": {
            "source": "KIGA",
            "captured_at": "2026-08-16T11:00:00+02:00",
            "status": "official",
            "result_version": "official-1",
            "scores": {"d": 5.2, "e": 7.9, "artistry": None, "neutral": 0.0, "final": 13.1},
        },
        "rights": {
            "download_allowed": True,
            "analysis_allowed": True,
            "training_allowed": False,
            "consent_reference": "fixture-consent",
            "retention_until": "2026-11-16",
            "access_policy": "competition-review",
        },
    }


def test_exchange_fixture_still_validates_against_existing_kiga_contract():
    errors = list(
        Draft202012Validator(
            EXCHANGE_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(record())
    )
    assert errors == []


def test_minimized_worker_payload_validates_against_new_task_schema():
    batch = plan_competition_batch(
        (record(),),
        batch_id="batch-1",
        analysis_profile_digest="a" * 64,
        requested_at=T0,
    )
    payload = batch.routines[0].task.worker_payload()
    errors = list(
        Draft202012Validator(
            TASK_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []


def test_task_schema_rejects_identity_official_and_request_time_fields():
    batch = plan_competition_batch(
        (record(),),
        batch_id="batch-1",
        analysis_profile_digest="a" * 64,
        requested_at=T0,
    )
    safe = batch.routines[0].task.worker_payload()
    for forbidden_field, forbidden_value in (
        ("official_result", {"final_score": 13.1}),
        ("athlete_external_id", "athlete-1"),
        ("competition_external_id", "competition-1"),
        ("routine_external_id", "routine-1"),
    ):
        mutated = dict(safe)
        mutated[forbidden_field] = forbidden_value
        assert list(Draft202012Validator(TASK_SCHEMA).iter_errors(mutated))
