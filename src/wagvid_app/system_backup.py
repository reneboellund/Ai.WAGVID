"""Portable full-system backup staging engine.

The engine creates a verified local backup set. Upload/replication to Wasabi, AWS S3,
ONTAP, VAST, Ootbi or another provider is a separate provider operation, so backup
format and integrity remain portable.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .recovery import pg_dump_command, sha256_file
from .recovery_manifest import (
    InventoryObject,
    build_object_inventory,
    build_system_backup_manifest,
)


class BackupError(RuntimeError):
    pass


CommandRunner = Callable[[Sequence[str]], None]


@dataclass(frozen=True)
class BackupDatabaseSource:
    host: str
    port: int
    database: str
    username: str
    server_version: str
    client_version: str


@dataclass(frozen=True)
class BackupApplicationIdentity:
    version: str
    git_sha: str
    migration_heads: tuple[str, ...]
    image_digest: str | None = None


@dataclass(frozen=True)
class BackupSet:
    root: Path
    manifest_path: Path
    database_path: Path
    config_path: Path
    inventory_path: Path
    manifest: dict


def _default_runner(command: Sequence[str]) -> None:
    subprocess.run(list(command), check=True)


def _atomic_json(path: Path, value: Mapping | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    encoded = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


_SENSITIVE_KEYS = {
    "password",
    "secret",
    "secret_key",
    "access_key",
    "access_key_id",
    "api_key",
    "private_key",
    "token",
}


def validate_portable_config(value, *, path: str = "config") -> None:
    """Reject likely plaintext operational secrets from the portable config bundle."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS and item is not None and item != "":
                if not (isinstance(item, str) and item.startswith("secret://")):
                    raise BackupError(f"Portable config contains inline secret at {child}")
            validate_portable_config(item, path=child)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            validate_portable_config(item, path=f"{path}[{index}]")


def create_backup_set(
    *,
    root: str | Path,
    backup_id: str,
    application: BackupApplicationIdentity,
    database: BackupDatabaseSource,
    portable_config: Mapping,
    inventory_objects: Iterable[InventoryObject],
    provider_inventory: Iterable[Mapping[str, object]] = (),
    rule_artifacts: Iterable[Mapping[str, object]] = (),
    model_artifacts: Iterable[Mapping[str, object]] = (),
    secret_refs: Iterable[str] = (),
    retention_class: str = "manual",
    encryption: Mapping[str, object] | None = None,
    created_at: datetime | None = None,
    runner: CommandRunner = _default_runner,
) -> BackupSet:
    """Create and verify the portable local staging set.

    PostgreSQL credentials are intentionally not accepted by this function. The caller
    supplies them to pg_dump through the deployment's protected PostgreSQL credential
    mechanism (for example PGPASSFILE/service configuration).
    """
    validate_portable_config(portable_config)
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BackupError("Backup timestamp must be timezone-aware")
    backup_root = Path(root).resolve() / backup_id
    if backup_root.exists() and any(backup_root.iterdir()):
        raise BackupError("Backup destination already contains data")
    backup_root.mkdir(parents=True, exist_ok=True)

    database_path = backup_root / "database" / "app.dump"
    config_path = backup_root / "config" / "portable-config.json"
    inventory_path = backup_root / "inventory" / "objects.json"
    manifest_path = backup_root / "manifest.json"
    database_path.parent.mkdir(parents=True, exist_ok=True)

    command = pg_dump_command(
        host=database.host,
        port=database.port,
        database=database.database,
        username=database.username,
        output_path=database_path,
        format_name="custom",
    )
    try:
        runner(command)
    except (subprocess.SubprocessError, OSError) as exc:
        raise BackupError(f"PostgreSQL backup failed: {type(exc).__name__}") from exc
    if not database_path.is_file() or database_path.stat().st_size == 0:
        raise BackupError("pg_dump did not create a non-empty database archive")

    inventory = build_object_inventory(inventory_objects, generated_at=timestamp)
    _atomic_json(config_path, dict(portable_config))
    _atomic_json(inventory_path, inventory)

    config_sha = sha256_file(config_path)
    inventory_sha = sha256_file(inventory_path)
    database_sha = sha256_file(database_path)

    manifest = build_system_backup_manifest(
        backup_id=backup_id,
        created_at=timestamp,
        application={
            "version": application.version,
            "git_sha": application.git_sha,
            "image_digest": application.image_digest,
            "migration_heads": list(application.migration_heads),
        },
        database={
            "engine": "postgresql",
            "server_version": database.server_version,
            "client_version": database.client_version,
            "format": "custom",
            "archive": str(database_path.relative_to(backup_root)),
            "sha256": database_sha,
        },
        config_bundle={
            "path": str(config_path.relative_to(backup_root)),
            "sha256": config_sha,
            "size_bytes": config_path.stat().st_size,
        },
        object_inventory={
            "path": str(inventory_path.relative_to(backup_root)),
            "sha256": inventory_sha,
            "size_bytes": inventory_path.stat().st_size,
        },
        provider_inventory=provider_inventory,
        rule_artifacts=rule_artifacts,
        model_artifacts=model_artifacts,
        secret_refs=secret_refs,
        included_components=("database", "config", "object-inventory"),
        excluded_components=("canonical-media-bytes",),
        retention_class=retention_class,
        encryption=encryption or {"encrypted": False, "method": None, "key_reference": None},
        verification_state="created",
    )
    _atomic_json(manifest_path, manifest)
    return BackupSet(
        root=backup_root,
        manifest_path=manifest_path,
        database_path=database_path,
        config_path=config_path,
        inventory_path=inventory_path,
        manifest=manifest,
    )
