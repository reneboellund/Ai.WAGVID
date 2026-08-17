"""Full-system restore preflight and staging plans.

Restore planning is read-only. Provider checks are injected so the same control-plane
logic can validate media on Wasabi, AWS S3, ONTAP, VAST, Ootbi or shared file storage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .recovery import pg_restore_command, verify_artifact


@dataclass(frozen=True)
class RestorePreflight:
    allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    restore_command: tuple[str, ...] | None


ObjectChecker = Callable[[Mapping[str, object]], tuple[bool, str | None]]


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read recovery artifact {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Recovery artifact {path.name} must contain a JSON object")
    return value


def restore_preflight(
    backup_root: str | Path,
    *,
    database_host: str,
    database_port: int,
    database_name: str,
    database_username: str,
    available_secret_refs: frozenset[str],
    object_checker: ObjectChecker | None = None,
    compatible_application_versions: frozenset[str] | None = None,
) -> RestorePreflight:
    root = Path(backup_root).resolve()
    blockers: list[str] = []
    warnings: list[str] = []
    manifest_path = root / "manifest.json"
    try:
        manifest = _load_json(manifest_path)
    except ValueError as exc:
        return RestorePreflight(False, (str(exc),), (), None)

    if manifest.get("schema") != "ai.wagvid.system-backup.v1":
        blockers.append("unsupported-backup-manifest-schema")
    verification = manifest.get("verification", {})
    if not isinstance(verification, Mapping) or verification.get("state") != "verified":
        blockers.append("backup-is-not-verified")

    application = manifest.get("application", {})
    backup_version = application.get("version") if isinstance(application, Mapping) else None
    if compatible_application_versions is not None and backup_version not in (
        compatible_application_versions
    ):
        blockers.append(f"application-version-not-compatible:{backup_version}")

    database = manifest.get("database", {})
    config_bundle = manifest.get("config_bundle", {})
    object_inventory = manifest.get("object_inventory", {})
    for label, artifact in (
        ("database", database),
        ("config", config_bundle),
        ("object-inventory", object_inventory),
    ):
        if not isinstance(artifact, Mapping) or "path" not in artifact or "sha256" not in artifact:
            blockers.append(f"invalid-artifact-reference:{label}")
            continue
        result = verify_artifact(root, artifact)
        if not result.ok:
            blockers.append(f"artifact-verification-failed:{label}:{result.reason}")

    required_secrets = {
        str(value) for value in manifest.get("secret_refs", []) if isinstance(value, str)
    }
    missing_secrets = sorted(required_secrets - available_secret_refs)
    blockers.extend(f"missing-secret:{secret}" for secret in missing_secrets)

    inventory_path = None
    if isinstance(object_inventory, Mapping) and object_inventory.get("path"):
        try:
            inventory_path = root / str(object_inventory["path"])
            inventory_path = inventory_path.resolve()
            inventory_path.relative_to(root)
        except (ValueError, OSError):
            blockers.append("object-inventory-path-invalid")
            inventory_path = None

    if inventory_path and inventory_path.is_file():
        try:
            inventory = _load_json(inventory_path)
        except ValueError as exc:
            blockers.append(str(exc))
        else:
            if inventory.get("schema") != "ai.wagvid.system-object-inventory.v1":
                blockers.append("unsupported-object-inventory-schema")
            objects = inventory.get("objects", [])
            if not isinstance(objects, list):
                blockers.append("invalid-object-inventory")
            elif object_checker:
                for item in objects:
                    if not isinstance(item, Mapping):
                        blockers.append("invalid-object-inventory-entry")
                        continue
                    ok, reason = object_checker(item)
                    if not ok:
                        asset_id = item.get("asset_id", "unknown")
                        blockers.append(
                            f"object-unavailable:{asset_id}:{reason or 'provider-check-failed'}"
                        )
            elif objects:
                warnings.append("object-provider-content-not-checked")

    restore_command = None
    archive = database.get("path") if isinstance(database, Mapping) else None
    if not archive and isinstance(database, Mapping):
        archive = database.get("archive")
    if archive:
        archive_path = (root / str(archive)).resolve()
        try:
            archive_path.relative_to(root)
        except ValueError:
            blockers.append("database-archive-path-invalid")
        else:
            restore_command = tuple(
                pg_restore_command(
                    host=database_host,
                    port=database_port,
                    database=database_name,
                    username=database_username,
                    archive_path=archive_path,
                    clean=False,
                )
            )
    else:
        blockers.append("database-archive-missing")

    return RestorePreflight(
        allowed=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        restore_command=restore_command,
    )
