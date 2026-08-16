import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]


def test_android_device_contract() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "android-capture-device-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    instance = {
        "schema_version": "1.0.0",
        "device_id": "tripod-phone-1",
        "connection": {
            "discovery_order": ["mdns", "authenticated-udp", "manual-url"],
            "mdns_service": "_wagvid._tcp.local",
            "backend_url": "https://192.0.2.10:8443",
            "pairing_state": "paired",
            "certificate_fingerprint": "AA:BB:CC",
            "last_connected_at": "2026-08-16T12:00:00+02:00",
        },
        "archive": {
            "local_retention": "retain-after-upload",
            "automatic_deletion": False,
            "archive_directory": "content://wagvid/archive",
        },
        "upload_queue": {
            "persistent": True,
            "start_after_finalize": True,
            "concurrency": 1,
            "items": [
                {
                    "capture_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
                    "local_uri": "content://wagvid/archive/video.mp4",
                    "sha256": "a" * 64,
                    "state": "queued",
                    "attempts": 0,
                    "uploaded_bytes": 0,
                    "remote_uri": None,
                    "last_error": None,
                    "local_retained": True,
                }
            ],
        },
    }
    errors = list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(instance)
    )
    assert errors == []
