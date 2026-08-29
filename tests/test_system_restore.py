import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from wagvid_app.recovery_manifest import InventoryObject
from wagvid_app.system_backup import (
    BackupApplicationIdentity,
    BackupDatabaseSource,
    create_backup_set,
)
from wagvid_app.system_restore import restore_preflight


def _fake_pg_dump(command):
    output = Path(command[command.index("--file") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"portable-postgresql-archive")


def _create_backup(tmp_path):
    backup = create_backup_set(
        root=tmp_path,
        backup_id="backup-restore",
        application=BackupApplicationIdentity(
            version="1.0.0",
            git_sha="a" * 40,
            migration_heads=("0011_mediaasset_source_metadata",),
        ),
        database=BackupDatabaseSource(
            host="db.internal",
            port=5432,
            database="wagvid",
            username="backup",
            server_version="17.6",
            client_version="17.6",
        ),
        portable_config={"storage": {"credential_ref": "secret://storage/primary"}},
        inventory_objects=[
            InventoryObject(
                asset_id="media-1",
                organization_id="org-1",
                provider_id="primary",
                provider_type="wasabi",
                bucket="originals",
                key="org-1/media-1.mp4",
                size_bytes=123,
                sha256="b" * 64,
            )
        ],
        secret_refs=["secret://database/password", "secret://storage/primary"],
        created_at=datetime(2026, 8, 17, 1, 30, tzinfo=UTC),
        runner=_fake_pg_dump,
    )
    manifest = json.loads(backup.manifest_path.read_text())
    manifest["verification"] = {
        "state": "verified",
        "verified_at": "2026-08-17T01:31:00Z",
        "failure_reason": None,
    }
    backup.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return backup


def _preflight(backup, **overrides):
    values = {
        "database_host": "restore-db.internal",
        "database_port": 5432,
        "database_name": "wagvid_restore",
        "database_username": "restore",
        "available_secret_refs": frozenset(
            {"secret://database/password", "secret://storage/primary"}
        ),
        "compatible_application_versions": frozenset({"1.0.0"}),
    }
    values.update(overrides)
    return restore_preflight(backup.root, **values)


def test_verified_backup_can_stage_non_destructive_restore(tmp_path):
    backup = _create_backup(tmp_path)
    result = _preflight(backup)
    assert result.allowed is True
    assert result.blockers == ()
    assert "object-provider-content-not-checked" in result.warnings
    assert result.restore_command is not None
    assert "--clean" not in result.restore_command
    assert "--if-exists" not in result.restore_command
    assert str(backup.database_path) == result.restore_command[-1]


def test_restore_blocks_unverified_backup(tmp_path):
    backup = _create_backup(tmp_path)
    manifest = json.loads(backup.manifest_path.read_text())
    manifest["verification"]["state"] = "created"
    backup.manifest_path.write_text(json.dumps(manifest))
    result = _preflight(backup)
    assert result.allowed is False
    assert "backup-is-not-verified" in result.blockers


def test_restore_blocks_missing_secret_reference(tmp_path):
    backup = _create_backup(tmp_path)
    result = _preflight(
        backup,
        available_secret_refs=frozenset({"secret://database/password"}),
    )
    assert result.allowed is False
    assert "missing-secret:secret://storage/primary" in result.blockers


def test_restore_blocks_corrupted_database_archive(tmp_path):
    backup = _create_backup(tmp_path)
    backup.database_path.write_bytes(b"corrupt")
    result = _preflight(backup)
    assert result.allowed is False
    assert any(
        blocker.startswith("artifact-verification-failed:database:SHA-256 mismatch")
        for blocker in result.blockers
    )


def test_restore_uses_provider_object_checker_without_modifying_storage(tmp_path):
    backup = _create_backup(tmp_path)
    checked = []

    def checker(item):
        checked.append(item["asset_id"])
        return True, None

    result = _preflight(backup, object_checker=checker)
    assert result.allowed is True
    assert checked == ["media-1"]
    assert "object-provider-content-not-checked" not in result.warnings


def test_restore_blocks_missing_provider_object(tmp_path):
    backup = _create_backup(tmp_path)

    def checker(item):
        return False, "not-found"

    result = _preflight(backup, object_checker=checker)
    assert result.allowed is False
    assert "object-unavailable:media-1:not-found" in result.blockers


def test_restore_blocks_incompatible_application_release(tmp_path):
    backup = _create_backup(tmp_path)
    result = _preflight(
        backup,
        compatible_application_versions=frozenset({"2.0.0"}),
    )
    assert result.allowed is False
    assert "application-version-not-compatible:1.0.0" in result.blockers


def test_restore_detects_inventory_tampering_even_if_json_remains_valid(tmp_path):
    backup = _create_backup(tmp_path)
    inventory = json.loads(backup.inventory_path.read_text())
    inventory["objects"][0]["sha256"] = hashlib.sha256(b"wrong").hexdigest()
    backup.inventory_path.write_text(json.dumps(inventory))
    result = _preflight(backup)
    assert result.allowed is False
    assert any(
        blocker.startswith("artifact-verification-failed:object-inventory:SHA-256 mismatch")
        for blocker in result.blockers
    )
