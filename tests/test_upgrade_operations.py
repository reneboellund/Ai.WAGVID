import json
from datetime import UTC, datetime, timedelta

import pytest

from wagvid_app.recovery import UpgradePreflight
from wagvid_app.upgrade_operations import (
    UpgradeEnvironmentSnapshot,
    UpgradeError,
    UpgradeEvent,
    UpgradeIdentity,
    UpgradePhase,
    append_upgrade_event,
    environment_upgrade_preflight,
    maintenance_readiness,
    merge_installation_config,
    post_upgrade_verification,
    read_upgrade_journal,
    restore_promotion_gate,
    rollback_plan,
    validate_data_preservation_plan,
)


NOW = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
IDENTITY = UpgradeIdentity(
    upgrade_id="upgrade-001",
    source_version="0.1.0",
    target_version="0.2.0",
    backup_id="backup-pre-upgrade",
    initiated_by="admin-1",
)


def test_environment_preflight_adds_db_disk_secret_provider_worker_and_device_gates():
    base = UpgradePreflight(True, warnings=("release-warning",))
    snapshot = UpgradeEnvironmentSnapshot(
        database_reachable=False,
        migration_graph_clean=False,
        storage_routing_clean=False,
        available_disk_bytes=100,
        required_disk_bytes=200,
        available_secret_refs=frozenset({"secret://db"}),
        required_secret_refs=frozenset({"secret://db", "secret://storage"}),
        incompatible_workers=("worker-old",),
        incompatible_devices=("android-old",),
        provider_blockers=("originals-unreachable",),
    )
    result = environment_upgrade_preflight(base, snapshot)
    assert not result.allowed
    assert "database-unreachable" in result.blockers
    assert "migration-graph-unknown-or-dirty" in result.blockers
    assert "storage-routing-drift" in result.blockers
    assert any(item.startswith("insufficient-disk-headroom") for item in result.blockers)
    assert "missing-secret:secret://storage" in result.blockers
    assert "provider-blocker:originals-unreachable" in result.blockers
    assert "incompatible-worker:worker-old" in result.blockers
    assert "incompatible-device:android-old" in result.blockers

    healthy = environment_upgrade_preflight(
        base,
        UpgradeEnvironmentSnapshot(
            database_reachable=True,
            migration_graph_clean=True,
            storage_routing_clean=True,
            available_disk_bytes=1000,
            required_disk_bytes=300,
            available_secret_refs=frozenset({"secret://db"}),
            required_secret_refs=frozenset({"secret://db"}),
        ),
    )
    assert healthy.allowed
    assert "disk-headroom-allows-staging-rehearsal" in healthy.warnings


def test_maintenance_requires_preflight_and_all_mutating_work_drained():
    preflight = UpgradePreflight(True, warnings=("extra-check",))
    blocked = maintenance_readiness(
        preflight=preflight,
        active_uploads=1,
        active_jobs=2,
        worker_leases=0,
        devices_recording=1,
    )
    assert not blocked.ready
    assert "active-uploads:1" in blocked.blockers
    assert "active-analysis-jobs:2" in blocked.blockers
    assert "devices-recording:1" in blocked.blockers

    ready = maintenance_readiness(
        preflight=preflight,
        active_uploads=0,
        active_jobs=0,
        worker_leases=0,
        devices_recording=0,
    )
    assert ready.ready
    assert "extra-check" in ready.warnings


def test_post_upgrade_verification_blocks_reopen_until_required_checks_pass():
    failed = post_upgrade_verification(
        migration_heads_match=True,
        django_checks_pass=True,
        database_integrity_pass=True,
        providers_healthy=False,
        workers_compatible=True,
        registries_load=True,
        auth_check_pass=True,
        backup_catalog_readable=True,
        sampled_media_pass=None,
    )
    assert not failed.passed
    assert "storage-provider-health-failed" in failed.blockers
    assert "sampled-media-reference-check-not-run" in failed.warnings

    passed = post_upgrade_verification(
        migration_heads_match=True,
        django_checks_pass=True,
        database_integrity_pass=True,
        providers_healthy=True,
        workers_compatible=True,
        registries_load=True,
        auth_check_pass=True,
        backup_catalog_readable=True,
        sampled_media_pass=True,
    )
    assert passed.passed


def test_restore_promotion_requires_secrets_objects_migrations_and_explicit_production_phrase():
    staging = restore_promotion_gate(
        restore_preflight_allowed=True,
        database_restored=True,
        secrets_rebound=True,
        object_inventory_verified=True,
        migrations_match=True,
        system_checks_pass=True,
        target_is_production=False,
    )
    assert staging.allowed
    assert "staging-restore-remains-write-isolated" in staging.warnings

    production = restore_promotion_gate(
        restore_preflight_allowed=True,
        database_restored=True,
        secrets_rebound=True,
        object_inventory_verified=True,
        migrations_match=True,
        system_checks_pass=True,
        target_is_production=True,
    )
    assert not production.allowed
    assert "explicit-production-promotion-confirmation-required" in production.blockers

    approved = restore_promotion_gate(
        restore_preflight_allowed=True,
        database_restored=True,
        secrets_rebound=True,
        object_inventory_verified=True,
        migrations_match=True,
        system_checks_pass=True,
        target_is_production=True,
        confirmation="PROMOTE RECOVERED SYSTEM TO PRODUCTION",
    )
    assert approved.allowed


def test_rollback_distinguishes_code_only_from_database_restore_and_never_moves_media():
    code = rollback_plan(IDENTITY, target_rollback_compatible=True, database_changed=False)
    assert code.mode == "code-only"
    assert code.keep_media_unchanged
    assert not code.restore_database_to_staging

    database = rollback_plan(IDENTITY, target_rollback_compatible=False, database_changed=True)
    assert database.mode == "restore-pre-upgrade-backup"
    assert database.restore_database_to_staging
    assert database.keep_media_unchanged
    assert any("unchanged object providers" in step for step in database.steps)


def test_config_upgrade_adds_defaults_without_overwriting_customer_or_unknown_values():
    existing = {
        "storage": {"provider": "vast", "custom_extension": {"future": True}},
        "ui": {"language": "da"},
    }
    defaults = {
        "storage": {"provider": "wasabi", "timeout": 30},
        "ui": {"language": "en", "theme": "system"},
        "new_feature": {"enabled": False},
    }
    merged = merge_installation_config(existing, defaults)
    assert merged["storage"]["provider"] == "vast"
    assert merged["storage"]["timeout"] == 30
    assert merged["storage"]["custom_extension"] == {"future": True}
    assert merged["ui"] == {"language": "da", "theme": "system"}
    assert merged["new_feature"] == {"enabled": False}
    assert existing["storage"].get("timeout") is None


def test_data_preservation_rejects_database_reset_media_delete_and_unstaged_contract_removal():
    blockers = validate_data_preservation_plan(
        operations=[
            {"action": "recreate-database"},
            {"action": "delete-canonical-media"},
            {"action": "move-media"},
            {"action": "remove-schema-representation", "deprecation_window_complete": False},
        ]
    )
    assert any("recreate-database" in item for item in blockers)
    assert any("delete-canonical-media" in item for item in blockers)
    assert any("media-move-requires-separate" in item for item in blockers)
    assert any("schema-contract-removal-not-staged" in item for item in blockers)


def test_upgrade_journal_is_hash_chained_identity_locked_and_phase_gated(tmp_path):
    journal = tmp_path / "upgrades.jsonl"
    phases = (
        UpgradePhase.PLANNED,
        UpgradePhase.MAINTENANCE,
        UpgradePhase.DRAINING,
        UpgradePhase.BACKUP_VERIFIED,
        UpgradePhase.APPLYING,
        UpgradePhase.VERIFYING,
        UpgradePhase.READY_TO_REOPEN,
        UpgradePhase.COMPLETED,
    )
    for index, phase in enumerate(phases):
        append_upgrade_event(
            journal,
            UpgradeEvent(IDENTITY, phase, NOW + timedelta(seconds=index), {"step": index}),
        )
    records = read_upgrade_journal(journal)
    assert [record["phase"] for record in records] == [phase.value for phase in phases]
    assert records[-1]["backup_id"] == "backup-pre-upgrade"

    with pytest.raises(UpgradeError, match="Invalid upgrade phase transition"):
        append_upgrade_event(
            journal,
            UpgradeEvent(IDENTITY, UpgradePhase.MAINTENANCE, NOW + timedelta(minutes=1)),
        )

    text = journal.read_text(encoding="utf-8")
    first = json.loads(text.splitlines()[0])
    first["backup_id"] = "different-backup"
    lines = text.splitlines()
    lines[0] = json.dumps(first, sort_keys=True)
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(UpgradeError, match="hash mismatch"):
        read_upgrade_journal(journal)


def test_failed_upgrade_can_only_move_to_staged_rollback(tmp_path):
    journal = tmp_path / "failed.jsonl"
    append_upgrade_event(journal, UpgradeEvent(IDENTITY, UpgradePhase.PLANNED, NOW))
    append_upgrade_event(
        journal,
        UpgradeEvent(IDENTITY, UpgradePhase.FAILED, NOW + timedelta(seconds=1), {"reason": "preflight"}),
    )
    append_upgrade_event(
        journal,
        UpgradeEvent(IDENTITY, UpgradePhase.ROLLBACK_STAGED, NOW + timedelta(seconds=2)),
    )
    assert read_upgrade_journal(journal)[-1]["phase"] == "rollback-staged"
