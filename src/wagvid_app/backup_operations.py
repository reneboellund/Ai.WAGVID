"""Operational backup verification, catalog and retention primitives.

These helpers make `verified` an earned state rather than a manifest label. They do not
contact PostgreSQL or storage directly; command execution and provider sampling are
injected by the operational layer and ordinary CI uses fixtures/fakes only.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from .recovery import safe_relative_path, sha256_file, verify_artifact


class BackupCatalogError(RuntimeError):
    pass


class BackupState(StrEnum):
    CREATED = "created"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


_ALLOWED_TRANSITIONS = {
    BackupState.CREATED: frozenset({BackupState.VERIFYING, BackupState.FAILED}),
    BackupState.VERIFYING: frozenset({BackupState.VERIFIED, BackupState.FAILED}),
    BackupState.VERIFIED: frozenset({BackupState.EXPIRED}),
    BackupState.FAILED: frozenset(),
    BackupState.EXPIRED: frozenset(),
}


@dataclass(frozen=True)
class BackupCatalogEvent:
    backup_id: str
    state: BackupState
    occurred_at: datetime
    actor: str
    reason: str | None = None
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.backup_id or not self.actor:
            raise ValueError("backup_id and actor are required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("Backup catalog timestamp must be timezone-aware")


@dataclass(frozen=True)
class BackupVerificationResult:
    ok: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    archive_entries: int
    manifest: dict


@dataclass(frozen=True)
class BackupRetentionPolicy:
    keep_daily: int = 14
    keep_weekly: int = 8
    keep_monthly: int = 12

    def __post_init__(self) -> None:
        if min(self.keep_daily, self.keep_weekly, self.keep_monthly) < 0:
            raise ValueError("Retention generations cannot be negative")


CommandCapture = Callable[[Sequence[str]], str]
ObjectSampler = Callable[[Mapping[str, object]], tuple[bool, str | None]]


def _default_capture(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command), check=True, text=True, capture_output=True
    )
    return completed.stdout


def pg_restore_list_command(
    archive_path: str | Path, *, executable: str = "pg_restore"
) -> list[str]:
    """Build the non-mutating archive readability check used before backup verification."""
    return [executable, "--list", str(archive_path)]


def _load_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupCatalogError(f"Cannot read {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise BackupCatalogError(f"{path.name} must contain a JSON object")
    return value


def verify_backup_set(
    root: str | Path,
    *,
    command_capture: CommandCapture = _default_capture,
    object_sampler: ObjectSampler | None = None,
    sample_limit: int = 0,
) -> BackupVerificationResult:
    """Verify a completed staging set without restoring or mutating production state."""

    backup_root = Path(root).resolve()
    blockers: list[str] = []
    warnings: list[str] = []
    archive_entries = 0
    manifest_path = backup_root / "manifest.json"
    try:
        manifest = _load_json_object(manifest_path)
    except BackupCatalogError as exc:
        return BackupVerificationResult(False, (str(exc),), (), 0, {})

    if manifest.get("schema") != "ai.wagvid.system-backup.v1":
        blockers.append("unsupported-backup-manifest-schema")

    database = manifest.get("database")
    database_path: Path | None = None
    if not isinstance(database, Mapping) or not database.get("archive") or not database.get("sha256"):
        blockers.append("invalid-database-artifact-reference")
    else:
        try:
            database_path = safe_relative_path(backup_root, str(database["archive"]))
        except ValueError as exc:
            blockers.append(f"database-archive-path-invalid:{exc}")
        else:
            if not database_path.is_file():
                blockers.append("database-archive-missing")
            elif sha256_file(database_path) != str(database["sha256"]):
                blockers.append("database-archive-sha256-mismatch")
            else:
                try:
                    listing = command_capture(pg_restore_list_command(database_path))
                except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
                    blockers.append(f"pg-restore-list-failed:{type(exc).__name__}")
                else:
                    archive_entries = sum(
                        1
                        for line in listing.splitlines()
                        if line.strip() and not line.lstrip().startswith(";")
                    )
                    if archive_entries == 0:
                        blockers.append("pg-restore-list-empty")

    for label, field in (("config", "config_bundle"), ("object-inventory", "object_inventory")):
        artifact = manifest.get(field)
        if not isinstance(artifact, Mapping) or "path" not in artifact or "sha256" not in artifact:
            blockers.append(f"invalid-artifact-reference:{label}")
            continue
        result = verify_artifact(backup_root, artifact)
        if not result.ok:
            blockers.append(f"artifact-verification-failed:{label}:{result.reason}")

    inventory_ref = manifest.get("object_inventory")
    if isinstance(inventory_ref, Mapping) and inventory_ref.get("path"):
        try:
            inventory_path = safe_relative_path(backup_root, str(inventory_ref["path"]))
            inventory = _load_json_object(inventory_path)
        except (ValueError, BackupCatalogError) as exc:
            blockers.append(f"object-inventory-invalid:{exc}")
        else:
            if inventory.get("schema") != "ai.wagvid.system-object-inventory.v1":
                blockers.append("unsupported-object-inventory-schema")
            objects = inventory.get("objects")
            if not isinstance(objects, list):
                blockers.append("invalid-object-inventory")
            elif object_sampler and sample_limit > 0:
                sample = sorted(
                    (item for item in objects if isinstance(item, Mapping)),
                    key=lambda item: str(item.get("asset_id", "")),
                )[:sample_limit]
                for item in sample:
                    ok, reason = object_sampler(item)
                    if not ok:
                        blockers.append(
                            f"sampled-object-verification-failed:{item.get('asset_id', 'unknown')}:{reason or 'unknown'}"
                        )
            elif objects:
                warnings.append("object-bytes-not-sampled")

    application = manifest.get("application", {})
    if not isinstance(application, Mapping) or application.get("git_sha") in (None, ""):
        blockers.append("application-git-sha-missing")
    if not isinstance(application, Mapping) or not application.get("migration_heads"):
        blockers.append("migration-heads-missing")

    return BackupVerificationResult(
        ok=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        archive_entries=archive_entries,
        manifest=manifest,
    )


def finalized_manifest(
    verification: BackupVerificationResult,
    *,
    verified_at: datetime,
) -> dict:
    """Return the schema-valid final manifest after successful archive/integrity verification."""
    if not verification.ok:
        raise BackupCatalogError("Cannot finalize an unverified backup")
    if verified_at.tzinfo is None or verified_at.utcoffset() is None:
        raise ValueError("verified_at must be timezone-aware")
    manifest = json.loads(json.dumps(verification.manifest))
    current = manifest.get("verification", {})
    if isinstance(current, Mapping) and current.get("state") == BackupState.VERIFIED.value:
        raise BackupCatalogError("Backup manifest is already finalized as verified")
    # Keep detailed archive/list evidence in the append-only catalog event metadata; the
    # manifest itself remains exactly within the published v1 schema.
    manifest["verification"] = {
        "state": BackupState.VERIFIED.value,
        "verified_at": verified_at.astimezone(UTC).isoformat(),
        "failure_reason": None,
    }
    return manifest


def write_final_manifest(path: str | Path, manifest: Mapping[str, object]) -> None:
    """Atomically replace a pre-final manifest exactly once; verified manifests are immutable."""
    destination = Path(path)
    if destination.exists():
        current = _load_json_object(destination)
        verification = current.get("verification", {})
        if isinstance(verification, Mapping) and verification.get("state") == BackupState.VERIFIED.value:
            raise BackupCatalogError("Verified backup manifests are immutable")
    temporary = destination.with_suffix(destination.suffix + ".partial")
    payload = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _event_payload(event: BackupCatalogEvent, previous_hash: str | None) -> dict:
    return {
        "backup_id": event.backup_id,
        "state": event.state.value,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "actor": event.actor,
        "reason": event.reason,
        "metadata": dict(event.metadata or {}),
        "previous_hash": previous_hash,
    }


def _event_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_catalog(path: str | Path) -> tuple[dict, ...]:
    catalog = Path(path)
    if not catalog.exists():
        return ()
    records: list[dict] = []
    previous_hash = None
    for line_number, line in enumerate(catalog.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BackupCatalogError(f"Invalid backup catalog JSON at line {line_number}") from exc
        if not isinstance(record, dict):
            raise BackupCatalogError(f"Invalid backup catalog record at line {line_number}")
        event_hash = record.pop("event_hash", None)
        if record.get("previous_hash") != previous_hash:
            raise BackupCatalogError(f"Backup catalog hash chain broken at line {line_number}")
        calculated = _event_hash(record)
        if event_hash != calculated:
            raise BackupCatalogError(f"Backup catalog event hash mismatch at line {line_number}")
        record["event_hash"] = event_hash
        records.append(record)
        previous_hash = event_hash
    return tuple(records)


def append_catalog_event(path: str | Path, event: BackupCatalogEvent) -> str:
    """Append one hash-chained transition and reject invalid state regressions."""
    records = read_catalog(path)
    current_state: BackupState | None = None
    for record in records:
        if record.get("backup_id") == event.backup_id:
            current_state = BackupState(str(record["state"]))
    if current_state is None:
        if event.state != BackupState.CREATED:
            raise BackupCatalogError("First backup catalog event must be created")
    elif event.state not in _ALLOWED_TRANSITIONS[current_state]:
        raise BackupCatalogError(
            f"Invalid backup state transition {current_state.value}->{event.state.value}"
        )

    previous_hash = records[-1]["event_hash"] if records else None
    payload = _event_payload(event, previous_hash)
    event_hash = _event_hash(payload)
    record = dict(payload)
    record["event_hash"] = event_hash
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event_hash


def retention_keep_ids(
    backups: Iterable[tuple[str, datetime]],
    *,
    now: datetime,
    policy: BackupRetentionPolicy,
) -> frozenset[str]:
    """Select deterministic daily/weekly/monthly generations from verified backups."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    ordered = sorted(backups, key=lambda item: (item[1], item[0]), reverse=True)
    keep: set[str] = set()
    daily: set[tuple[int, int]] = set()
    weekly: set[tuple[int, int]] = set()
    monthly: set[tuple[int, int]] = set()
    for backup_id, created_at in ordered:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("backup timestamps must be timezone-aware")
        stamp = created_at.astimezone(UTC)
        age = now.astimezone(UTC) - stamp
        if age.total_seconds() < 0:
            raise ValueError("backup timestamp cannot be in the future")
        day_key = (stamp.year, stamp.timetuple().tm_yday)
        week = stamp.isocalendar()
        week_key = (week.year, week.week)
        month_key = (stamp.year, stamp.month)
        if (
            policy.keep_daily
            and age <= timedelta(days=policy.keep_daily - 1)
            and len(daily) < policy.keep_daily
            and day_key not in daily
        ):
            daily.add(day_key)
            keep.add(backup_id)
            continue
        if policy.keep_weekly and len(weekly) < policy.keep_weekly and week_key not in weekly:
            weekly.add(week_key)
            keep.add(backup_id)
            continue
        if policy.keep_monthly and len(monthly) < policy.keep_monthly and month_key not in monthly:
            monthly.add(month_key)
            keep.add(backup_id)
    return frozenset(keep)
