import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path("android")


def test_android_project_has_offline_first_capture_dependencies_and_permissions():
    build = (ROOT / "app/build.gradle.kts").read_text(encoding="utf-8")
    manifest = (ROOT / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    for dependency in ("camera-video", "room-runtime", "work-runtime-ktx", "security-crypto"):
        assert dependency in build
    assert "android.permission.CAMERA" in manifest
    assert "android.permission.RECORD_AUDIO" in manifest
    assert 'android:allowBackup="false"' in manifest
    assert 'cleartextTrafficPermitted="false"' in (
        ROOT / "app/src/main/res/xml/network_security_config.xml"
    ).read_text(encoding="utf-8")


def test_local_archive_is_retained_and_upload_queue_is_persistent():
    database = (
        ROOT
        / "app/src/main/java/com/boellund/wagvid/capture/data/CaptureDatabase.kt"
    ).read_text(encoding="utf-8")
    worker = (
        ROOT / "app/src/main/java/com/boellund/wagvid/capture/upload/UploadWorker.kt"
    ).read_text(encoding="utf-8")
    assert "localRetained: Boolean = true" in database
    assert "upload_queue" in database
    assert "delete" not in worker.lower()
    assert "uploadedBytes" in worker
    assert "Result.retry()" in worker


def test_command_contract_validates_remote_capture_context():
    schema = json.loads(Path("schemas/device-command-v1.schema.json").read_text())
    command = {
        "command_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "command": "start",
        "expected_device_state": "ready",
        "payload": {
            "capture_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
            "gymnast_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf7",
            "kind": "drill",
            "apparatus": "BB",
        },
        "expires_at": "2026-08-16T18:00:00Z",
    }
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(command)
    ) == []
    del command["payload"]["gymnast_id"]
    assert list(Draft202012Validator(schema).iter_errors(command))
