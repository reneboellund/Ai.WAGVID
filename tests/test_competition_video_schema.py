import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "competition-video-v1.schema.json").read_text(encoding="utf-8")
)

EXAMPLE = {
    "schema": "ai.wagvid.competition-video.v1",
    "record_id": "record-001",
    "created_at": "2026-08-16T10:00:00+02:00",
    "competition": {
        "external_id": "kiga-competition-42",
        "provider": "KIGA",
        "name": "Example competition",
        "start_date": "2026-08-16",
        "end_date": "2026-08-16",
        "timezone": "Europe/Copenhagen",
        "venue": "Example Hall",
        "city": "Copenhagen",
        "country_code": "DK",
        "organizer": "Example organizer",
        "federation": None,
        "competition_level": "national",
        "rule_profile": "FIG-WAG-2025-2028@2026-05-04+draft.1",
    },
    "routine": {
        "external_id": "routine-99",
        "athlete_external_id": "athlete-7",
        "team_external_id": None,
        "apparatus": "BB",
        "round": "final",
        "rotation": 2,
        "start_order": 4,
        "performed_at": "2026-08-16T13:30:00+02:00",
        "age_category": "junior",
        "competition_category": "individual",
    },
    "media": [
        {
            "media_id": "media-123",
            "camera_id": "camera-main",
            "view": "side",
            "download_uri": "https://kiga.example/download/signed-token",
            "sha256": "a" * 64,
            "captured_at": "2026-08-16T13:30:00+02:00",
            "content_type": "video/mp4",
            "size_bytes": 123456,
            "duration_ms": 90000,
        }
    ],
    "official_result": {
        "source": "KIGA competition result",
        "status": "official",
        "captured_at": "2026-08-16T15:00:00+02:00",
        "result_version": "1",
        "scores": {"d": 5.2, "e": 7.8, "artistry": None, "neutral": 0, "final": 13.0},
    },
    "analysis_link": None,
    "adjudication": {"status": "pending"},
    "learning": {"eligible": False, "label_tier": "unreviewed_official"},
    "rights": {
        "download_allowed": True,
        "analysis_allowed": True,
        "training_allowed": False,
        "retention_until": None,
        "consent_reference": None,
        "access_policy": "competition-participants",
    },
}


def errors_for(instance: dict) -> list:
    return list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(instance))


def test_example_competition_video_exchange_is_valid() -> None:
    assert errors_for(EXAMPLE) == []


def test_media_requires_content_hash() -> None:
    instance = deepcopy(EXAMPLE)
    del instance["media"][0]["sha256"]
    assert any("sha256" in error.message for error in errors_for(instance))


def test_training_rights_are_explicit() -> None:
    instance = deepcopy(EXAMPLE)
    del instance["rights"]["training_allowed"]
    assert any("training_allowed" in error.message for error in errors_for(instance))


def test_adjudication_rejects_unsupported_outcomes() -> None:
    instance = deepcopy(EXAMPLE)
    instance["adjudication"]["status"] = "official_is_always_truth"
    assert errors_for(instance)
