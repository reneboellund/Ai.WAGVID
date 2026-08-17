"""Provider-neutral backup, restore and upgrade safety helpers.

This module deliberately contains no provider I/O and does not execute PostgreSQL
commands. It builds deterministic plans that callers can approve and execute in an
operational layer with secrets supplied through environment/secret injection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ArtifactVerification:
    path: str
    expected_sha256: str
    actual_sha256: str | None
    ok: bool
    reason: str | None = None


@dataclass(frozen=True)
class UpgradePreflight:
    allowed: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_intermediate: str | None = None


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a local artifact without loading the whole file into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(root: str | Path, relative_path: str) -> Path:
    """Resolve a backup-manifest path while rejecting absolute/traversal paths."""
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("Backup artifact paths must be relative")
    root_path = Path(root).resolve()
    resolved = (root_path / candidate).resolve()
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Backup artifact path escapes the backup root") from exc
    return resolved


def verify_artifact(root: str | Path, artifact: Mapping[str, object]) -> ArtifactVerification:
    relative_path = str(artifact["path"])
    expected = str(artifact["sha256"])
    try:
        path = safe_relative_path(root, relative_path)
    except ValueError as exc:
        return ArtifactVerification(relative_path, expected, None, False, str(exc))
    if not path.is_file():
        return ArtifactVerification(relative_path, expected, None, False, "Artifact is missing")
    actual = sha256_file(path)
    if actual != expected:
        return ArtifactVerification(relative_path, expected, actual, False, "SHA-256 mismatch")
    return ArtifactVerification(relative_path, expected, actual, True)


def pg_dump_command(
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    output_path: str | Path,
    format_name: str = "custom",
    executable: str = "pg_dump",
) -> list[str]:
    """Build a portable pg_dump command with no password/secret in argv."""
    format_flag = {"custom": "c", "directory": "d"}.get(format_name)
    if format_flag is None:
        raise ValueError("Unsupported pg_dump format")
    return [
        executable,
        "--host",
        host,
        "--port",
        str(port),
        "--username",
        username,
        "--format",
        format_flag,
        "--file",
        str(output_path),
        "--no-password",
        database,
    ]


def pg_restore_command(
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    archive_path: str | Path,
    jobs: int = 1,
    clean: bool = False,
    executable: str = "pg_restore",
) -> list[str]:
    """Build a pg_restore command; production overwrite remains opt-in."""
    if jobs < 1:
        raise ValueError("pg_restore jobs must be at least 1")
    command = [
        executable,
        "--host",
        host,
        "--port",
        str(port),
        "--username",
        username,
        "--dbname",
        database,
        "--jobs",
        str(jobs),
        "--exit-on-error",
        "--no-password",
    ]
    if clean:
        command.extend(["--clean", "--if-exists"])
    command.append(str(archive_path))
    return command


def _matches_version(version: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(version, pattern) for pattern in patterns)


def release_upgrade_preflight(
    *,
    current_version: str,
    current_postgresql_major: str,
    current_migration_heads: Sequence[str],
    target_manifest: Mapping[str, object],
    verified_backup: bool,
    providers_reachable: bool = True,
) -> UpgradePreflight:
    """Evaluate manifest-level upgrade gates without mutating the installation."""
    blockers: list[str] = []
    warnings: list[str] = []
    required_intermediate: str | None = None

    supported_pg = {str(value) for value in target_manifest.get("supported_postgresql", [])}
    if current_postgresql_major not in supported_pg:
        blockers.append(
            f"PostgreSQL {current_postgresql_major} is not supported by the target release"
        )

    upgrade_from = target_manifest.get("upgrade_from", {})
    direct = upgrade_from.get("direct", []) if isinstance(upgrade_from, Mapping) else []
    intermediate = (
        upgrade_from.get("requires_intermediate", {})
        if isinstance(upgrade_from, Mapping)
        else {}
    )
    if not _matches_version(current_version, [str(item) for item in direct]):
        if isinstance(intermediate, Mapping):
            for pattern, required in intermediate.items():
                if fnmatchcase(current_version, str(pattern)):
                    required_intermediate = str(required)
                    blockers.append(
                        f"Upgrade requires intermediate release {required_intermediate}"
                    )
                    break
        if required_intermediate is None:
            blockers.append(f"No supported upgrade path from {current_version}")

    if not verified_backup:
        blockers.append("A verified pre-upgrade backup is required")
    if not providers_reachable:
        blockers.append("Required storage providers are not reachable")

    declared_target_heads = {str(value) for value in target_manifest.get("migration_heads", [])}
    if not declared_target_heads:
        blockers.append("Target release does not declare migration heads")
    if not current_migration_heads:
        blockers.append("Current migration state is unknown")

    required_preflight = {str(value) for value in target_manifest.get("required_preflight", [])}
    known_checks = {"verified-backup", "database-compatible", "providers-reachable"}
    unknown_checks = sorted(required_preflight - known_checks)
    if unknown_checks:
        warnings.append(
            "Target release declares additional preflight gates: " + ", ".join(unknown_checks)
        )

    return UpgradePreflight(
        allowed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        required_intermediate=required_intermediate,
    )
