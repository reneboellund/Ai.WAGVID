import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def errors_for(schema_name: str, instance: dict) -> list:
    schema = load_schema(schema_name)
    return list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance))


BACKUP = {
    "schema": "ai.wagvid.system-backup.v1",
    "backup_id": "backup-2026-08-17T010000Z",
    "created_at": "2026-08-17T01:00:00Z",
    "application": {
        "version": "1.0.0",
        "git_sha": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "migration_heads": ["0011_mediaasset_source_metadata"],
    },
    "database": {
        "engine": "postgresql",
        "server_version": "17.6",
        "client_version": "17.6",
        "format": "custom",
        "archive": "database/app.dump",
        "sha256": "c" * 64,
    },
    "config_bundle": {"path": "config/config.tar", "sha256": "d" * 64, "size_bytes": 42},
    "object_inventory": {"path": "inventory/objects.json", "sha256": "e" * 64, "size_bytes": 84},
    "provider_inventory": [{"provider_id": "primary", "provider_type": "wasabi", "capabilities": ["range", "multipart"]}],
    "rule_artifacts": [{"id": "FIG-WAG", "sha256": "f" * 64}],
    "model_artifacts": [],
    "secret_refs": ["secret://storage/primary/access-key"],
    "included_components": ["database", "config", "object-inventory"],
    "excluded_components": ["media-bytes"],
    "retention_class": "pre-upgrade",
    "encryption": {"encrypted": True, "method": "age", "key_reference": "kms://backup-key"},
    "verification": {"state": "verified", "verified_at": "2026-08-17T01:02:00Z", "failure_reason": None},
    "parent_backup_id": None,
}

INVENTORY = {
    "schema": "ai.wagvid.system-object-inventory.v1",
    "generated_at": "2026-08-17T01:00:00Z",
    "objects": [
        {
            "asset_id": "media-1",
            "organization_id": "org-1",
            "provider_id": "primary",
            "provider_type": "wasabi",
            "location": {"bucket": "originals", "key": "org-1/media-1.mp4", "filesystem": None, "path": None, "version_id": "v1"},
            "size_bytes": 1234,
            "sha256": "a" * 64,
            "retention_until": None,
            "legal_hold": False,
            "object_lock_mode": None,
            "protection_refs": ["replication:secondary"],
        }
    ],
}

RELEASE = {
    "schema": "ai.wagvid.release-manifest.v1",
    "version": "1.0.0",
    "git_sha": "a" * 40,
    "image_digest": "sha256:" + "b" * 64,
    "built_at": "2026-08-17T01:00:00Z",
    "supported_postgresql": ["17"],
    "migration_heads": ["0011_mediaasset_source_metadata"],
    "schemas": {"config": "v1", "storage": "v1", "rules": "v1", "models": "v1"},
    "upgrade_from": {"direct": ["0.9.x"], "requires_intermediate": {"0.8.x": "0.9.0"}},
    "breaking_changes": [],
    "rollback": {"code_only_supported": False, "database_restore_required_after_migration": True, "notes": "Use verified pre-upgrade backup."},
    "android": {"min_protocol": 1, "max_protocol": 1, "min_app_version": "1.0.0"},
    "required_preflight": ["verified-backup", "database-compatible", "providers-reachable"],
}


def test_system_backup_manifest_example_is_valid() -> None:
    assert errors_for("system-backup-v1.schema.json", BACKUP) == []


def test_system_backup_requires_database_hash() -> None:
    instance = deepcopy(BACKUP)
    del instance["database"]["sha256"]
    assert any("sha256" in error.message for error in errors_for("system-backup-v1.schema.json", instance))


def test_system_backup_secret_refs_do_not_accept_inline_assignment() -> None:
    instance = deepcopy(BACKUP)
    instance["secret_refs"] = ["password=hunter2"]
    assert errors_for("system-backup-v1.schema.json", instance)


def test_object_inventory_requires_hash_and_provider_location() -> None:
    assert errors_for("system-object-inventory-v1.schema.json", INVENTORY) == []
    instance = deepcopy(INVENTORY)
    del instance["objects"][0]["sha256"]
    assert errors_for("system-object-inventory-v1.schema.json", instance)


def test_release_manifest_example_is_valid() -> None:
    assert errors_for("release-manifest-v1.schema.json", RELEASE) == []


def test_release_manifest_requires_explicit_rollback_semantics() -> None:
    instance = deepcopy(RELEASE)
    del instance["rollback"]["database_restore_required_after_migration"]
    assert errors_for("release-manifest-v1.schema.json", instance)
