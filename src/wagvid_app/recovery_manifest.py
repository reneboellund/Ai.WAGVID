"""Deterministic builders for portable recovery manifests.

The builders consume already-discovered metadata. They do not contact storage providers,
run PostgreSQL commands or read secret values, which keeps backup planning testable and
provider-neutral.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class InventoryObject:
    asset_id: str
    organization_id: str
    provider_id: str
    provider_type: str
    size_bytes: int
    sha256: str
    bucket: str | None = None
    key: str | None = None
    filesystem: str | None = None
    path: str | None = None
    version_id: str | None = None
    retention_until: str | None = None
    legal_hold: bool | None = None
    object_lock_mode: str | None = None
    protection_refs: tuple[str, ...] = ()

    def as_manifest_entry(self) -> dict:
        object_location = {
            "bucket": self.bucket,
            "key": self.key,
            "filesystem": self.filesystem,
            "path": self.path,
            "version_id": self.version_id,
        }
        if not ((self.bucket and self.key) or (self.filesystem and self.path)):
            raise ValueError(
                f"Object {self.asset_id} requires bucket/key or filesystem/path location"
            )
        if len(self.sha256) != 64:
            raise ValueError(f"Object {self.asset_id} does not have a canonical SHA-256")
        if self.size_bytes < 0:
            raise ValueError(f"Object {self.asset_id} has a negative size")
        return {
            "asset_id": self.asset_id,
            "organization_id": self.organization_id,
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "location": object_location,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "retention_until": self.retention_until,
            "legal_hold": self.legal_hold,
            "object_lock_mode": self.object_lock_mode,
            "protection_refs": sorted(set(self.protection_refs)),
        }


def build_object_inventory(
    objects: Iterable[InventoryObject], *, generated_at: datetime | None = None
) -> dict:
    timestamp = generated_at or datetime.now(UTC)
    entries = [item.as_manifest_entry() for item in objects]
    entries.sort(
        key=lambda item: (
            item["organization_id"],
            item["provider_id"],
            item["asset_id"],
        )
    )
    return {
        "schema": "ai.wagvid.system-object-inventory.v1",
        "generated_at": timestamp.isoformat(),
        "objects": entries,
    }


def build_system_backup_manifest(
    *,
    backup_id: str,
    created_at: datetime,
    application: Mapping[str, object],
    database: Mapping[str, object],
    config_bundle: Mapping[str, object],
    object_inventory: Mapping[str, object],
    provider_inventory: Iterable[Mapping[str, object]] = (),
    rule_artifacts: Iterable[Mapping[str, object]] = (),
    model_artifacts: Iterable[Mapping[str, object]] = (),
    secret_refs: Iterable[str] = (),
    included_components: Iterable[str],
    excluded_components: Iterable[str] = (),
    retention_class: str,
    encryption: Mapping[str, object],
    verification_state: str = "created",
    parent_backup_id: str | None = None,
) -> dict:
    refs = sorted(set(secret_refs))
    for ref in refs:
        lowered = ref.casefold()
        if "password=" in lowered or "secret=" in lowered:
            raise ValueError("Secret references must not contain inline secret values")
    return {
        "schema": "ai.wagvid.system-backup.v1",
        "backup_id": backup_id,
        "created_at": created_at.isoformat(),
        "application": dict(application),
        "database": dict(database),
        "config_bundle": dict(config_bundle),
        "object_inventory": dict(object_inventory),
        "provider_inventory": sorted(
            (dict(item) for item in provider_inventory),
            key=lambda item: (str(item.get("provider_type", "")), str(item.get("provider_id", ""))),
        ),
        "rule_artifacts": sorted(
            (dict(item) for item in rule_artifacts), key=lambda item: str(item.get("id", ""))
        ),
        "model_artifacts": sorted(
            (dict(item) for item in model_artifacts), key=lambda item: str(item.get("id", ""))
        ),
        "secret_refs": refs,
        "included_components": sorted(set(included_components)),
        "excluded_components": sorted(set(excluded_components)),
        "retention_class": retention_class,
        "encryption": dict(encryption),
        "verification": {
            "state": verification_state,
            "verified_at": None,
            "failure_reason": None,
        },
        "parent_backup_id": parent_backup_id,
    }
