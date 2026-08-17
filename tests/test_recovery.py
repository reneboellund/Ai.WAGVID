import hashlib

import pytest

from wagvid_app.recovery import (
    pg_dump_command,
    pg_restore_command,
    release_upgrade_preflight,
    safe_relative_path,
    verify_artifact,
)


def target_manifest() -> dict:
    return {
        "supported_postgresql": ["17"],
        "migration_heads": ["0011_mediaasset_source_metadata"],
        "upgrade_from": {
            "direct": ["0.9.*", "1.0.*"],
            "requires_intermediate": {"0.8.*": "0.9.0"},
        },
        "required_preflight": [
            "verified-backup",
            "database-compatible",
            "providers-reachable",
        ],
    }


def test_safe_relative_path_stays_under_backup_root(tmp_path):
    assert safe_relative_path(tmp_path, "database/app.dump") == (
        tmp_path / "database" / "app.dump"
    ).resolve()
    with pytest.raises(ValueError, match="escapes"):
        safe_relative_path(tmp_path, "../outside.dump")
    with pytest.raises(ValueError, match="relative"):
        safe_relative_path(tmp_path, str((tmp_path / "absolute.dump").resolve()))


def test_verify_artifact_checks_sha256(tmp_path):
    path = tmp_path / "config.tar"
    payload = b"recoverable-config"
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    result = verify_artifact(tmp_path, {"path": "config.tar", "sha256": expected})
    assert result.ok is True
    mismatch = verify_artifact(tmp_path, {"path": "config.tar", "sha256": "0" * 64})
    assert mismatch.ok is False
    assert mismatch.reason == "SHA-256 mismatch"


def test_postgresql_commands_never_put_password_in_argv():
    dump = pg_dump_command(
        host="db.internal",
        port=5432,
        database="wagvid",
        username="backup_user",
        output_path="backup/app.dump",
    )
    restore = pg_restore_command(
        host="db.internal",
        port=5432,
        database="wagvid_restore",
        username="restore_user",
        archive_path="backup/app.dump",
        jobs=4,
    )
    rendered = " ".join(dump + restore).lower()
    assert "password=" not in rendered
    assert "secret=" not in rendered
    assert "--no-password" in dump
    assert "--no-password" in restore


def test_upgrade_preflight_accepts_supported_direct_upgrade():
    result = release_upgrade_preflight(
        current_version="0.9.8",
        current_postgresql_major="17",
        current_migration_heads=["0010_previous"],
        target_manifest=target_manifest(),
        verified_backup=True,
        providers_reachable=True,
    )
    assert result.allowed is True
    assert result.blockers == ()


def test_upgrade_preflight_requires_intermediate_release():
    result = release_upgrade_preflight(
        current_version="0.8.7",
        current_postgresql_major="17",
        current_migration_heads=["0010_previous"],
        target_manifest=target_manifest(),
        verified_backup=True,
    )
    assert result.allowed is False
    assert result.required_intermediate == "0.9.0"


def test_upgrade_preflight_blocks_without_backup_or_supported_database():
    result = release_upgrade_preflight(
        current_version="0.9.8",
        current_postgresql_major="16",
        current_migration_heads=["0010_previous"],
        target_manifest=target_manifest(),
        verified_backup=False,
        providers_reachable=False,
    )
    assert result.allowed is False
    assert any("PostgreSQL 16" in blocker for blocker in result.blockers)
    assert any("verified pre-upgrade backup" in blocker for blocker in result.blockers)
    assert any("storage providers" in blocker for blocker in result.blockers)


def test_restore_clean_mode_is_explicit():
    normal = pg_restore_command(
        host="localhost",
        port=5432,
        database="staging",
        username="restore",
        archive_path="backup.dump",
    )
    destructive = pg_restore_command(
        host="localhost",
        port=5432,
        database="staging",
        username="restore",
        archive_path="backup.dump",
        clean=True,
    )
    assert "--clean" not in normal
    assert "--clean" in destructive
    assert "--if-exists" in destructive
