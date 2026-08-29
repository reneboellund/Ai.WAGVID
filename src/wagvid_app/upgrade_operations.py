"""Safe upgrade transaction, maintenance and rollback planning.

This module does not replace application code, run migrations or touch media. It turns
#73's operational rules into explicit state transitions and append-only journal entries
that deployment adapters can execute for Compose, systemd or future Kubernetes modes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .recovery import UpgradePreflight


class UpgradeError(RuntimeError):
    pass


class UpgradePhase(StrEnum):
    PLANNED = "planned"
    MAINTENANCE = "maintenance"
    DRAINING = "draining"
    BACKUP_VERIFIED = "backup-verified"
    APPLYING = "applying"
    VERIFYING = "verifying"
    READY_TO_REOPEN = "ready-to-reopen"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLBACK_STAGED = "rollback-staged"


_ALLOWED = {
    UpgradePhase.PLANNED: frozenset({UpgradePhase.MAINTENANCE, UpgradePhase.FAILED}),
    UpgradePhase.MAINTENANCE: frozenset({UpgradePhase.DRAINING, UpgradePhase.FAILED}),
    UpgradePhase.DRAINING: frozenset({UpgradePhase.BACKUP_VERIFIED, UpgradePhase.FAILED}),
    UpgradePhase.BACKUP_VERIFIED: frozenset({UpgradePhase.APPLYING, UpgradePhase.FAILED}),
    UpgradePhase.APPLYING: frozenset({UpgradePhase.VERIFYING, UpgradePhase.FAILED}),
    UpgradePhase.VERIFYING: frozenset({UpgradePhase.READY_TO_REOPEN, UpgradePhase.FAILED}),
    UpgradePhase.READY_TO_REOPEN: frozenset({UpgradePhase.COMPLETED, UpgradePhase.FAILED}),
    UpgradePhase.FAILED: frozenset({UpgradePhase.ROLLBACK_STAGED}),
    UpgradePhase.ROLLBACK_STAGED: frozenset(),
    UpgradePhase.COMPLETED: frozenset(),
}


@dataclass(frozen=True)
class UpgradeIdentity:
    upgrade_id: str
    source_version: str
    target_version: str
    backup_id: str
    initiated_by: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.upgrade_id,
                self.source_version,
                self.target_version,
                self.backup_id,
                self.initiated_by,
            )
        ):
            raise ValueError("Upgrade identity fields are required")
        if self.source_version == self.target_version:
            raise ValueError("Source and target release must differ")


@dataclass(frozen=True)
class UpgradeEvent:
    identity: UpgradeIdentity
    phase: UpgradePhase
    occurred_at: datetime
    details: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Upgrade event timestamp must be timezone-aware")


@dataclass(frozen=True)
class UpgradeEnvironmentSnapshot:
    database_reachable: bool
    migration_graph_clean: bool
    storage_routing_clean: bool
    available_disk_bytes: int
    required_disk_bytes: int
    available_secret_refs: frozenset[str] = frozenset()
    required_secret_refs: frozenset[str] = frozenset()
    incompatible_workers: tuple[str, ...] = ()
    incompatible_devices: tuple[str, ...] = ()
    provider_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.available_disk_bytes < 0 or self.required_disk_bytes < 0:
            raise ValueError("Disk byte values cannot be negative")


@dataclass(frozen=True)
class MaintenanceReadiness:
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PostUpgradeVerification:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RollbackPlan:
    mode: str
    source_version: str
    failed_target_version: str
    backup_id: str
    keep_media_unchanged: bool
    restore_database_to_staging: bool
    steps: tuple[str, ...]


@dataclass(frozen=True)
class RestorePromotionGate:
    allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def environment_upgrade_preflight(
    base: UpgradePreflight,
    snapshot: UpgradeEnvironmentSnapshot,
) -> UpgradePreflight:
    """Add installation/runtime gates to the release-manifest compatibility preflight."""
    blockers = list(base.blockers)
    warnings = list(base.warnings)
    if not snapshot.database_reachable:
        blockers.append("database-unreachable")
    if not snapshot.migration_graph_clean:
        blockers.append("migration-graph-unknown-or-dirty")
    if not snapshot.storage_routing_clean:
        blockers.append("storage-routing-drift")
    if snapshot.available_disk_bytes < snapshot.required_disk_bytes:
        blockers.append(
            f"insufficient-disk-headroom:required={snapshot.required_disk_bytes}:available={snapshot.available_disk_bytes}"
        )
    missing_secrets = sorted(snapshot.required_secret_refs - snapshot.available_secret_refs)
    blockers.extend(f"missing-secret:{value}" for value in missing_secrets)
    blockers.extend(f"provider-blocker:{value}" for value in snapshot.provider_blockers)
    blockers.extend(f"incompatible-worker:{value}" for value in sorted(snapshot.incompatible_workers))
    blockers.extend(f"incompatible-device:{value}" for value in sorted(snapshot.incompatible_devices))
    if snapshot.available_disk_bytes >= snapshot.required_disk_bytes * 2 and snapshot.required_disk_bytes:
        warnings.append("disk-headroom-allows-staging-rehearsal")
    return UpgradePreflight(
        allowed=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        required_intermediate=base.required_intermediate,
    )


def maintenance_readiness(
    *,
    preflight: UpgradePreflight,
    active_uploads: int,
    active_jobs: int,
    worker_leases: int,
    devices_recording: int,
    allow_read_only_sessions: bool = True,
) -> MaintenanceReadiness:
    blockers = list(preflight.blockers)
    warnings = list(preflight.warnings)
    for name, count in (
        ("active-uploads", active_uploads),
        ("active-analysis-jobs", active_jobs),
        ("active-worker-leases", worker_leases),
        ("devices-recording", devices_recording),
    ):
        if count < 0:
            raise ValueError(f"{name} cannot be negative")
        if count:
            blockers.append(f"{name}:{count}")
    if allow_read_only_sessions:
        warnings.append("read-only-sessions-may-remain-available-during-maintenance")
    return MaintenanceReadiness(
        ready=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def post_upgrade_verification(
    *,
    migration_heads_match: bool,
    django_checks_pass: bool,
    database_integrity_pass: bool,
    providers_healthy: bool,
    workers_compatible: bool,
    registries_load: bool,
    auth_check_pass: bool,
    backup_catalog_readable: bool,
    sampled_media_pass: bool | None = None,
) -> PostUpgradeVerification:
    blockers: list[str] = []
    warnings: list[str] = []
    required = {
        "migration-heads-mismatch": migration_heads_match,
        "django-system-checks-failed": django_checks_pass,
        "database-integrity-check-failed": database_integrity_pass,
        "storage-provider-health-failed": providers_healthy,
        "worker-runtime-incompatible": workers_compatible,
        "rule-or-model-registry-load-failed": registries_load,
        "authentication-check-failed": auth_check_pass,
        "backup-catalog-unreadable": backup_catalog_readable,
    }
    blockers.extend(reason for reason, passed in required.items() if not passed)
    if sampled_media_pass is False:
        blockers.append("sampled-media-reference-check-failed")
    elif sampled_media_pass is None:
        warnings.append("sampled-media-reference-check-not-run")
    return PostUpgradeVerification(
        passed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def restore_promotion_gate(
    *,
    restore_preflight_allowed: bool,
    database_restored: bool,
    secrets_rebound: bool,
    object_inventory_verified: bool,
    migrations_match: bool,
    system_checks_pass: bool,
    target_is_production: bool,
    confirmation: str | None = None,
) -> RestorePromotionGate:
    blockers: list[str] = []
    warnings: list[str] = []
    required = {
        "restore-preflight-not-approved": restore_preflight_allowed,
        "database-not-restored": database_restored,
        "secrets-not-rebound": secrets_rebound,
        "object-inventory-not-verified": object_inventory_verified,
        "migration-state-not-exact": migrations_match,
        "system-checks-failed": system_checks_pass,
    }
    blockers.extend(reason for reason, passed in required.items() if not passed)
    if target_is_production:
        if confirmation != "PROMOTE RECOVERED SYSTEM TO PRODUCTION":
            blockers.append("explicit-production-promotion-confirmation-required")
    else:
        warnings.append("staging-restore-remains-write-isolated")
    return RestorePromotionGate(
        allowed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def rollback_plan(
    identity: UpgradeIdentity,
    *,
    target_rollback_compatible: bool,
    database_changed: bool,
) -> RollbackPlan:
    if target_rollback_compatible and not database_changed:
        return RollbackPlan(
            mode="code-only",
            source_version=identity.source_version,
            failed_target_version=identity.target_version,
            backup_id=identity.backup_id,
            keep_media_unchanged=True,
            restore_database_to_staging=False,
            steps=(
                "keep system in maintenance",
                "replace application code/image with source release",
                "run source-release system and provider checks",
                "explicitly reopen writes",
            ),
        )
    return RollbackPlan(
        mode="restore-pre-upgrade-backup",
        source_version=identity.source_version,
        failed_target_version=identity.target_version,
        backup_id=identity.backup_id,
        keep_media_unchanged=True,
        restore_database_to_staging=True,
        steps=(
            "keep system in maintenance",
            "restore verified pre-upgrade database backup to new/staging database",
            "validate restored database with source application release",
            "rebind unchanged object providers without moving or deleting media",
            "verify object inventory and historical provenance",
            "perform explicit cutback only after integrity checks",
        ),
    )


def merge_installation_config(
    existing: Mapping[str, object],
    new_defaults: Mapping[str, object],
) -> dict:
    """Add new default keys recursively without overwriting installation/customer values."""
    result: dict = json.loads(json.dumps(existing))
    for key, default_value in new_defaults.items():
        if key not in result:
            result[key] = json.loads(json.dumps(default_value))
        elif isinstance(result[key], Mapping) and isinstance(default_value, Mapping):
            result[key] = merge_installation_config(result[key], default_value)
    return result


def validate_data_preservation_plan(
    *,
    operations: Iterable[Mapping[str, object]],
) -> tuple[str, ...]:
    """Reject deployment plans that implicitly destroy production data or canonical media."""
    blockers: list[str] = []
    forbidden = {
        "drop-database",
        "recreate-database",
        "truncate-table",
        "delete-canonical-media",
        "overwrite-canonical-media",
        "reset-audit-history",
    }
    for index, operation in enumerate(operations):
        action = str(operation.get("action", ""))
        if action in forbidden:
            blockers.append(f"forbidden-upgrade-operation:{index}:{action}")
        if action == "move-media" and not operation.get("separate_migration_plan"):
            blockers.append(f"media-move-requires-separate-migration-plan:{index}")
        if action == "remove-schema-representation" and not operation.get("deprecation_window_complete"):
            blockers.append(f"schema-contract-removal-not-staged:{index}")
    return tuple(blockers)


def _payload(event: UpgradeEvent, previous_hash: str | None) -> dict:
    identity = event.identity
    return {
        "upgrade_id": identity.upgrade_id,
        "source_version": identity.source_version,
        "target_version": identity.target_version,
        "backup_id": identity.backup_id,
        "initiated_by": identity.initiated_by,
        "phase": event.phase.value,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "details": dict(event.details or {}),
        "previous_hash": previous_hash,
    }


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_upgrade_journal(path: str | Path) -> tuple[dict, ...]:
    journal = Path(path)
    if not journal.exists():
        return ()
    previous = None
    records: list[dict] = []
    for line_number, line in enumerate(journal.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UpgradeError(f"Invalid upgrade journal JSON at line {line_number}") from exc
        if not isinstance(record, dict):
            raise UpgradeError(f"Invalid upgrade journal record at line {line_number}")
        event_hash = record.pop("event_hash", None)
        if record.get("previous_hash") != previous:
            raise UpgradeError(f"Upgrade journal hash chain broken at line {line_number}")
        calculated = _hash(record)
        if event_hash != calculated:
            raise UpgradeError(f"Upgrade journal event hash mismatch at line {line_number}")
        record["event_hash"] = event_hash
        records.append(record)
        previous = event_hash
    return tuple(records)


def append_upgrade_event(path: str | Path, event: UpgradeEvent) -> str:
    records = read_upgrade_journal(path)
    same_upgrade = [record for record in records if record.get("upgrade_id") == event.identity.upgrade_id]
    if not same_upgrade:
        if event.phase != UpgradePhase.PLANNED:
            raise UpgradeError("First upgrade event must be planned")
    else:
        latest = same_upgrade[-1]
        for field, expected in (
            ("source_version", event.identity.source_version),
            ("target_version", event.identity.target_version),
            ("backup_id", event.identity.backup_id),
            ("initiated_by", event.identity.initiated_by),
        ):
            if latest.get(field) != expected:
                raise UpgradeError(f"Upgrade identity changed after journal creation: {field}")
        current = UpgradePhase(str(latest["phase"]))
        if event.phase not in _ALLOWED[current]:
            raise UpgradeError(f"Invalid upgrade phase transition {current.value}->{event.phase.value}")

    previous = records[-1]["event_hash"] if records else None
    payload = _payload(event, previous)
    event_hash = _hash(payload)
    record = dict(payload)
    record["event_hash"] = event_hash
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event_hash
