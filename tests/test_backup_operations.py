import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from wagvid_app.backup_operations import (
    BackupCatalogError,
    BackupCatalogEvent,
    BackupRetentionPolicy,
    BackupState,
    append_catalog_event,
    finalized_manifest,
    pg_restore_list_command,
    read_catalog,
    retention_keep_ids,
    verify_backup_set,
    write_final_manifest,
)


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_backup(root: Path) -> dict:
    database = b"fake-postgres-custom-archive"
    config = json.dumps({"storage": {"credential": "secret://storage/main"}}, sort_keys=True).encode()
    inventory_value = {
        "schema": "ai.wagvid.system-object-inventory.v1",
        "generated_at": NOW.isoformat(),
        "objects": [
            {
                "asset_id": "asset-001",
                "organization_id": "org-1",
                "provider_id": "primary",
                "provider_type": "aws-s3",
                "container": "originals",
                "key": "org/video.mp4",
                "version_id": "v1",
                "size_bytes": 10,
                "sha256": "a" * 64,
            }
        ],
    }
    inventory = json.dumps(inventory_value, sort_keys=True).encode()
    (root / "database").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "inventory").mkdir()
    (root / "database/app.dump").write_bytes(database)
    (root / "config/portable-config.json").write_bytes(config)
    (root / "inventory/objects.json").write_bytes(inventory)
    manifest = {
        "schema": "ai.wagvid.system-backup.v1",
        "backup_id": "backup-001",
        "created_at": NOW.isoformat(),
        "application": {
            "version": "0.2.0",
            "git_sha": "b" * 40,
            "image_digest": None,
            "migration_heads": ["wagvid_app.0011"],
        },
        "database": {
            "engine": "postgresql",
            "server_version": "17.6",
            "client_version": "17.6",
            "format": "custom",
            "archive": "database/app.dump",
            "sha256": _sha(database),
        },
        "config_bundle": {
            "path": "config/portable-config.json",
            "sha256": _sha(config),
            "size_bytes": len(config),
        },
        "object_inventory": {
            "path": "inventory/objects.json",
            "sha256": _sha(inventory),
            "size_bytes": len(inventory),
        },
        "provider_inventory": [],
        "rule_artifacts": [],
        "model_artifacts": [],
        "secret_refs": ["secret://storage/main"],
        "included_components": ["database", "config", "object-inventory"],
        "excluded_components": ["canonical-media-bytes"],
        "retention_class": "daily",
        "encryption": {"encrypted": False, "method": None, "key_reference": None},
        "verification": {"state": "created", "verified_at": None, "failure_reason": None},
        "parent_backup_id": None,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_pg_restore_listing_is_read_only_command():
    command = pg_restore_list_command("backup.dump")
    assert command == ["pg_restore", "--list", "backup.dump"]
    assert "--clean" not in command


def test_backup_becomes_verified_only_after_hash_archive_and_optional_object_checks(tmp_path):
    _write_backup(tmp_path)
    captured = []

    def listing(command):
        captured.append(tuple(command))
        return "; archive header\n1; 1259 1 TABLE public gymnast owner\n2; 0 1 TABLE DATA public gymnast owner\n"

    result = verify_backup_set(
        tmp_path,
        command_capture=listing,
        object_sampler=lambda item: (item["sha256"] == "a" * 64, None),
        sample_limit=1,
    )
    assert result.ok
    assert result.archive_entries == 2
    assert captured[0][:2] == ("pg_restore", "--list")
    assert "object-bytes-not-sampled" not in result.warnings

    final = finalized_manifest(result, verified_at=NOW + timedelta(minutes=1))
    assert final["verification"]["state"] == "verified"
    assert "archive_entries" not in final["verification"]

    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/system-backup-v1.schema.json").read_text()
    )
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(final)
    ) == []
    write_final_manifest(tmp_path / "manifest.json", final)
    with pytest.raises(BackupCatalogError, match="immutable"):
        write_final_manifest(tmp_path / "manifest.json", final)


def test_corrupt_archive_or_empty_pg_restore_listing_cannot_be_verified(tmp_path):
    manifest = _write_backup(tmp_path)
    (tmp_path / "database/app.dump").write_bytes(b"corrupted")
    result = verify_backup_set(tmp_path, command_capture=lambda command: "1 TABLE x")
    assert not result.ok
    assert "database-archive-sha256-mismatch" in result.blockers

    (tmp_path / "database/app.dump").write_bytes(b"fake-postgres-custom-archive")
    manifest["database"]["sha256"] = _sha(b"fake-postgres-custom-archive")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    empty = verify_backup_set(tmp_path, command_capture=lambda command: "; comments only\n")
    assert not empty.ok
    assert "pg-restore-list-empty" in empty.blockers


def test_sampled_missing_object_blocks_backup_verification(tmp_path):
    _write_backup(tmp_path)
    result = verify_backup_set(
        tmp_path,
        command_capture=lambda command: "1 TABLE x\n",
        object_sampler=lambda item: (False, "not-found"),
        sample_limit=1,
    )
    assert not result.ok
    assert any(item.startswith("sampled-object-verification-failed:asset-001") for item in result.blockers)


def test_backup_catalog_is_append_only_hash_chained_and_transition_gated(tmp_path):
    catalog = tmp_path / "catalog.jsonl"
    append_catalog_event(
        catalog,
        BackupCatalogEvent("b1", BackupState.CREATED, NOW, "system"),
    )
    append_catalog_event(
        catalog,
        BackupCatalogEvent("b1", BackupState.VERIFYING, NOW + timedelta(seconds=1), "system"),
    )
    append_catalog_event(
        catalog,
        BackupCatalogEvent(
            "b1",
            BackupState.VERIFIED,
            NOW + timedelta(seconds=2),
            "system",
            metadata={"archive_entries": 42},
        ),
    )
    records = read_catalog(catalog)
    assert [item["state"] for item in records] == ["created", "verifying", "verified"]
    assert records[-1]["metadata"]["archive_entries"] == 42

    with pytest.raises(BackupCatalogError, match="Invalid backup state transition"):
        append_catalog_event(
            catalog,
            BackupCatalogEvent("b1", BackupState.VERIFYING, NOW + timedelta(seconds=3), "system"),
        )

    text = catalog.read_text(encoding="utf-8")
    catalog.write_text(text.replace('"actor": "system"', '"actor": "attacker"', 1), encoding="utf-8")
    with pytest.raises(BackupCatalogError, match="hash mismatch"):
        read_catalog(catalog)


def test_retention_selection_is_deterministic_and_never_keeps_future_backup():
    backups = [
        (f"b-{days}", NOW - timedelta(days=days))
        for days in (0, 1, 2, 8, 15, 32, 65, 95)
    ]
    keep = retention_keep_ids(
        backups,
        now=NOW,
        policy=BackupRetentionPolicy(keep_daily=3, keep_weekly=2, keep_monthly=3),
    )
    assert {"b-0", "b-1", "b-2"}.issubset(keep)
    assert len(keep) <= 8
    with pytest.raises(ValueError, match="future"):
        retention_keep_ids(
            [("future", NOW + timedelta(seconds=1))],
            now=NOW,
            policy=BackupRetentionPolicy(),
        )
