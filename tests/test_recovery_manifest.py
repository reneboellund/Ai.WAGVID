from datetime import UTC, datetime

import pytest

from wagvid_app.recovery_manifest import (
    InventoryObject,
    build_object_inventory,
    build_system_backup_manifest,
)


def test_object_inventory_is_deterministic_and_provider_neutral():
    timestamp = datetime(2026, 8, 17, 1, 30, tzinfo=UTC)
    inventory = build_object_inventory(
        [
            InventoryObject(
                asset_id="b",
                organization_id="org-1",
                provider_id="vast-primary",
                provider_type="vast-s3",
                bucket="originals",
                key="org-1/b.mp4",
                size_bytes=20,
                sha256="b" * 64,
            ),
            InventoryObject(
                asset_id="a",
                organization_id="org-1",
                provider_id="anf-stage",
                provider_type="azure-netapp-files",
                filesystem="anf-volume-1",
                path="/wagvid/a.mp4",
                size_bytes=10,
                sha256="a" * 64,
                protection_refs=("snapshot:snap-1", "replication:west-europe"),
            ),
        ],
        generated_at=timestamp,
    )
    assert inventory["schema"] == "ai.wagvid.system-object-inventory.v1"
    assert [item["asset_id"] for item in inventory["objects"]] == ["a", "b"]
    assert inventory["objects"][0]["provider_type"] == "azure-netapp-files"
    assert inventory["objects"][1]["provider_type"] == "vast-s3"


def test_inventory_rejects_unlocated_or_unhashed_evidence():
    with pytest.raises(ValueError, match="requires bucket/key"):
        build_object_inventory(
            [
                InventoryObject(
                    asset_id="bad",
                    organization_id="org",
                    provider_id="provider",
                    provider_type="s3",
                    size_bytes=1,
                    sha256="a" * 64,
                )
            ]
        )
    with pytest.raises(ValueError, match="canonical SHA-256"):
        build_object_inventory(
            [
                InventoryObject(
                    asset_id="bad",
                    organization_id="org",
                    provider_id="provider",
                    provider_type="s3",
                    bucket="b",
                    key="k",
                    size_bytes=1,
                    sha256="short",
                )
            ]
        )


def test_backup_manifest_builder_sorts_references_without_secret_values():
    manifest = build_system_backup_manifest(
        backup_id="backup-1",
        created_at=datetime(2026, 8, 17, 1, 30, tzinfo=UTC),
        application={"version": "1.0.0", "git_sha": "a" * 40, "migration_heads": ["0011"]},
        database={
            "engine": "postgresql",
            "server_version": "17",
            "client_version": "17",
            "format": "custom",
            "archive": "database.dump",
            "sha256": "b" * 64,
        },
        config_bundle={"path": "config.tar", "sha256": "c" * 64, "size_bytes": 1},
        object_inventory={"path": "objects.json", "sha256": "d" * 64, "size_bytes": 1},
        provider_inventory=[
            {"provider_id": "secondary", "provider_type": "aws-s3"},
            {"provider_id": "primary", "provider_type": "wasabi"},
        ],
        secret_refs=["secret://z", "secret://a", "secret://a"],
        included_components=["database", "config"],
        retention_class="daily",
        encryption={"encrypted": True, "method": "age", "key_reference": "kms://backup"},
    )
    assert manifest["secret_refs"] == ["secret://a", "secret://z"]
    assert [item["provider_type"] for item in manifest["provider_inventory"]] == [
        "aws-s3",
        "wasabi",
    ]


def test_backup_manifest_builder_rejects_inline_secret_assignment():
    with pytest.raises(ValueError, match="inline secret"):
        build_system_backup_manifest(
            backup_id="backup-1",
            created_at=datetime.now(UTC),
            application={},
            database={},
            config_bundle={},
            object_inventory={},
            secret_refs=["password=hunter2"],
            included_components=["database"],
            retention_class="manual",
            encryption={"encrypted": False},
        )
