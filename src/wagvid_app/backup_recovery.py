"""Provider-neutral backup manifests and verification primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from .models import StorageConnection, StoredObjectRecord, SystemBackup

BACKUP_SCHEMA = "ai.wagvid.system-backup-plan.v1"


def canonical_digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def migration_heads() -> list[str]:
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    return sorted(f"{app}.{name}" for app, name in loader.graph.leaf_nodes())


def storage_inventory() -> list[dict]:
    return [
        {
            "logical_object_id": str(record.id),
            "organization_id": str(record.organization_id),
            "provider": record.connection.provider,
            "connection_id": str(record.connection_id),
            "bucket": record.bucket.bucket_name,
            "key": record.object_key,
            "version_id": record.version_id,
            "size_bytes": record.size_bytes,
            "sha256": record.content_sha256,
            "state": record.state,
            "billable_until": record.billable_until.isoformat(),
            "retention_until": record.retention_until.isoformat()
            if record.retention_until
            else None,
            "legal_hold": record.legal_hold,
        }
        for record in StoredObjectRecord.objects.select_related("connection", "bucket").order_by(
            "organization_id", "id"
        )
    ]


def non_secret_configuration() -> dict:
    return {
        "storage_connections": [
            {
                "id": str(item.id),
                "organization_id": str(item.organization_id),
                "provider": item.provider,
                "endpoint": item.endpoint,
                "region": item.region,
                "auth_mode": item.auth_mode,
                "access_key_secret_ref": item.access_key_secret_ref,
                "secret_key_secret_ref": item.secret_key_secret_ref,
                "custom_ca_secret_ref": item.custom_ca_secret_ref,
                "governance_profile": item.governance_profile,
                "routing_revision": item.routing_revision,
                "bucket_map": item.existing_bucket_map,
            }
            for item in StorageConnection.objects.order_by("organization_id", "id")
        ]
    }


@dataclass(frozen=True)
class PostgresBackupCommand:
    argv: tuple[str, ...]
    required_environment: tuple[str, ...]


def postgres_backup_command(*, output_path: str) -> PostgresBackupCommand:
    if not output_path or "\n" in output_path:
        raise ValueError("safe backup output path is required")
    return PostgresBackupCommand(
        (
            "pg_dump",
            "--format=custom",
            "--compress=9",
            "--no-password",
            f"--file={output_path}",
        ),
        ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"),
    )


@transaction.atomic
def create_backup_plan(
    *, requested_by, purpose: str, destination: str, release: str, git_sha: str
) -> SystemBackup:
    inventory = storage_inventory()
    config = non_secret_configuration()
    manifest = {
        "schema": BACKUP_SCHEMA,
        "created_at": timezone.now().isoformat(),
        "release": release,
        "git_sha": git_sha,
        "migration_heads": migration_heads(),
        "database": {"format": "pg_dump-custom", "artifact": "database.dump", "sha256": None},
        "configuration": {
            "artifact": "configuration.json",
            "sha256": canonical_digest(config),
        },
        "object_inventory": {
            "artifact": "object-inventory.json",
            "count": len(inventory),
            "sha256": canonical_digest(inventory),
        },
        "secret_values_included": False,
        "required_secret_references": sorted(
            {
                value
                for item in config["storage_connections"]
                for value in (
                    item["access_key_secret_ref"],
                    item["secret_key_secret_ref"],
                    item["custom_ca_secret_ref"],
                )
                if value
            }
        ),
        "media_bytes_included": False,
    }
    backup = SystemBackup.objects.create(
        purpose=purpose,
        requested_by=requested_by,
        destination=destination,
        application_release=release,
        git_sha=git_sha,
        migration_heads=manifest["migration_heads"],
        manifest=manifest,
        expires_at=timezone.now() + timedelta(days=35),
    )
    backup.manifest["backup_id"] = str(backup.id)
    backup.manifest_sha256 = canonical_digest(backup.manifest)
    backup.save(update_fields=["manifest", "manifest_sha256", "updated_at"])
    membership = requested_by.wagvid_memberships.filter(active=True).first()
    if membership:
        membership.organization.audit_events.create(
            actor=requested_by,
            action="system.backup-planned",
            object_type="system-backup",
            object_id=str(backup.id),
            metadata={"purpose": purpose, "destination": destination},
        )
    return backup


@transaction.atomic
def verify_backup(backup_id, *, database_sha256: str, actor) -> SystemBackup:
    backup = SystemBackup.objects.select_for_update().get(pk=backup_id)
    if backup.state not in {SystemBackup.State.CREATED, SystemBackup.State.FAILED}:
        raise ValueError("backup is not in a verifiable state")
    checks = {
        "manifest_digest": canonical_digest(backup.manifest) == backup.manifest_sha256,
        "schema": backup.manifest.get("schema") == BACKUP_SCHEMA,
        "database_sha256": len(database_sha256) == 64
        and all(character in "0123456789abcdef" for character in database_sha256),
        "configuration_digest": bool(backup.manifest.get("configuration", {}).get("sha256")),
        "inventory_digest": bool(backup.manifest.get("object_inventory", {}).get("sha256")),
        "migration_heads": bool(backup.migration_heads),
    }
    backup.verification = checks
    if all(checks.values()):
        backup.manifest["database"]["sha256"] = database_sha256
        backup.manifest_sha256 = canonical_digest(backup.manifest)
        backup.state = SystemBackup.State.VERIFIED
        backup.verified_at = timezone.now()
    else:
        backup.state = SystemBackup.State.FAILED
    backup.save(
        update_fields=[
            "manifest", "manifest_sha256", "state", "verification", "verified_at", "updated_at"
        ]
    )
    actor.wagvid_memberships.first().organization.audit_events.create(
        actor=actor,
        action="system.backup-verified" if backup.state == SystemBackup.State.VERIFIED else "system.backup-failed",
        object_type="system-backup",
        object_id=str(backup.id),
        metadata={"checks": checks, "destination": backup.destination},
    )
    return backup


def restore_preflight(backup: SystemBackup, *, available_secret_references: set[str]) -> dict:
    required = set(backup.manifest.get("required_secret_references", []))
    missing = sorted(required - available_secret_references)
    return {
        "backup_verified": backup.state == SystemBackup.State.VERIFIED,
        "manifest_valid": canonical_digest(backup.manifest) == backup.manifest_sha256,
        "missing_secret_references": missing,
        "object_count": backup.manifest.get("object_inventory", {}).get("count", 0),
        "objects_overwritten": False,
        "activation_allowed": backup.state == SystemBackup.State.VERIFIED and not missing,
        "staging_restore_allowed": backup.state == SystemBackup.State.VERIFIED,
    }
