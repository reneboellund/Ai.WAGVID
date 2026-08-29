import json
from datetime import UTC, datetime

import pytest

from wagvid_app.recovery_manifest import InventoryObject
from wagvid_app.system_backup import (
    BackupApplicationIdentity,
    BackupDatabaseSource,
    BackupError,
    create_backup_set,
    validate_portable_config,
)


def app():
    return BackupApplicationIdentity(
        version="1.0.0",
        git_sha="a" * 40,
        migration_heads=("0011_mediaasset_source_metadata",),
    )


def database():
    return BackupDatabaseSource(
        host="db.internal",
        port=5432,
        database="wagvid",
        username="backup",
        server_version="17.6",
        client_version="17.6",
    )


def inventory():
    return [
        InventoryObject(
            asset_id="media-1",
            organization_id="org-1",
            provider_id="primary",
            provider_type="wasabi",
            bucket="originals",
            key="org-1/media-1.mp4",
            size_bytes=10,
            sha256="b" * 64,
        )
    ]


def fake_pg_dump(command):
    output = command[command.index("--file") + 1]
    from pathlib import Path

    Path(output).write_bytes(b"portable-postgres-archive")


def test_backup_set_is_created_without_embedding_database_password(tmp_path):
    calls = []

    def runner(command):
        calls.append(list(command))
        fake_pg_dump(command)

    backup = create_backup_set(
        root=tmp_path,
        backup_id="backup-1",
        application=app(),
        database=database(),
        portable_config={
            "storage": {"credential_ref": "secret://storage/primary"},
            "django": {"allowed_hosts": ["wagvid.example"]},
        },
        inventory_objects=inventory(),
        secret_refs=["secret://database/password", "secret://storage/primary"],
        created_at=datetime(2026, 8, 17, 1, 0, tzinfo=UTC),
        runner=runner,
    )
    assert backup.manifest_path.is_file()
    assert backup.database_path.is_file()
    rendered = " ".join(calls[0]).casefold()
    assert "password=" not in rendered
    assert "--no-password" in calls[0]
    manifest = json.loads(backup.manifest_path.read_text())
    assert manifest["database"]["sha256"]
    assert manifest["object_inventory"]["sha256"]
    assert manifest["verification"]["state"] == "created"


def test_backup_set_refuses_nonempty_destination(tmp_path):
    target = tmp_path / "backup-1"
    target.mkdir()
    (target / "existing").write_text("do-not-overwrite")
    with pytest.raises(BackupError, match="already contains data"):
        create_backup_set(
            root=tmp_path,
            backup_id="backup-1",
            application=app(),
            database=database(),
            portable_config={},
            inventory_objects=[],
            runner=fake_pg_dump,
        )


def test_portable_config_rejects_plaintext_secret_values():
    with pytest.raises(BackupError, match="inline secret"):
        validate_portable_config({"database": {"password": "hunter2"}})
    validate_portable_config({"database": {"password": "secret://database/password"}})


def test_backup_set_requires_timezone_aware_timestamp(tmp_path):
    with pytest.raises(BackupError, match="timezone-aware"):
        create_backup_set(
            root=tmp_path,
            backup_id="backup-1",
            application=app(),
            database=database(),
            portable_config={},
            inventory_objects=[],
            created_at=datetime(2026, 8, 17, 1, 0),  # noqa: DTZ001 - verifies naive timestamps fail closed
            runner=fake_pg_dump,
        )


def test_backup_set_fails_if_pg_dump_does_not_produce_archive(tmp_path):
    with pytest.raises(BackupError, match="non-empty database archive"):
        create_backup_set(
            root=tmp_path,
            backup_id="backup-1",
            application=app(),
            database=database(),
            portable_config={},
            inventory_objects=[],
            runner=lambda command: None,
        )
