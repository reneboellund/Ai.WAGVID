"""Safe upgrade planning, maintenance state and backup gates."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .backup_recovery import migration_heads
from .models import (
    AnalysisJob,
    MaintenanceState,
    StorageConnection,
    SystemBackup,
    UpgradeJournal,
    UploadSession,
)


def upgrade_preflight(*, target_manifest: dict, maximum_backup_age_hours: int = 24) -> dict:
    latest = SystemBackup.objects.filter(
        state=SystemBackup.State.VERIFIED,
        verified_at__gte=timezone.now() - timedelta(hours=maximum_backup_age_hours),
    ).order_by("-verified_at").first()
    current_heads = [head for head in migration_heads() if head.startswith("wagvid_app.")]
    target_heads = sorted(target_manifest.get("migration_heads", []))
    active_jobs = AnalysisJob.objects.filter(
        state__in=[AnalysisJob.State.RUNNING, AnalysisJob.State.QUEUED]
    ).count()
    active_uploads = UploadSession.objects.filter(
        state__in=[UploadSession.State.OPEN, UploadSession.State.UPLOADING, UploadSession.State.VERIFYING]
    ).count()
    storage_blockers = list(
        StorageConnection.objects.filter(active=True).exclude(
            support_state__in=["validated", "unvalidated"]
        ).values_list("id", flat=True)
    )
    checks = {
        "verified_backup": bool(latest),
        "migration_path_known": bool(target_heads) and set(current_heads).issubset(set(target_heads)),
        "active_analysis_jobs": active_jobs,
        "active_uploads": active_uploads,
        "storage_blockers": [str(value) for value in storage_blockers],
        "target_release": target_manifest.get("version", ""),
        "rollback_compatible": bool(target_manifest.get("rollback", {}).get("code_only")),
    }
    blockers = []
    if not checks["verified_backup"]:
        blockers.append("recent-verified-backup-required")
    if not checks["migration_path_known"]:
        blockers.append("unknown-migration-path")
    if active_jobs:
        blockers.append("analysis-queue-not-drained")
    if active_uploads:
        blockers.append("uploads-not-drained")
    if storage_blockers:
        blockers.append("storage-provider-degraded")
    return {"ready": not blockers, "blockers": blockers, "checks": checks, "backup": latest}


@transaction.atomic
def plan_upgrade(*, actor, source_release: str, target_manifest: dict) -> UpgradeJournal:
    result = upgrade_preflight(target_manifest=target_manifest)
    journal = UpgradeJournal.objects.create(
        initiated_by=actor,
        source_release=source_release,
        target_release=target_manifest.get("version", "unknown"),
        target_manifest=target_manifest,
        backup=result["backup"],
        state=UpgradeJournal.State.PLANNED if result["ready"] else UpgradeJournal.State.BLOCKED,
        preflight={"ready": result["ready"], "blockers": result["blockers"], "checks": result["checks"]},
        migrations_planned=target_manifest.get("migration_heads", []),
        config_migrations=target_manifest.get("config_migrations", []),
    )
    actor.wagvid_memberships.first().organization.audit_events.create(
        actor=actor,
        action="system.upgrade-planned",
        object_type="upgrade-journal",
        object_id=str(journal.id),
        metadata={"target": journal.target_release, "blockers": result["blockers"]},
    )
    return journal


@transaction.atomic
def set_maintenance(*, actor, active: bool, reason: str) -> MaintenanceState:
    if active and not reason.strip():
        raise ValueError("maintenance reason is required")
    state, _ = MaintenanceState.objects.select_for_update().get_or_create(pk=1)
    state.active = active
    state.read_only = active
    state.reason = reason.strip() if active else ""
    state.entered_by = actor if active else None
    state.entered_at = timezone.now() if active else None
    state.save()
    actor.wagvid_memberships.first().organization.audit_events.create(
        actor=actor,
        action="system.maintenance-entered" if active else "system.maintenance-left",
        object_type="maintenance-state",
        object_id="1",
        reason=reason.strip(),
    )
    return state


@transaction.atomic
def transition_upgrade(*, journal_id, actor, action: str, verification: dict | None = None):
    journal = UpgradeJournal.objects.select_for_update().get(pk=journal_id)
    transitions = {
        (UpgradeJournal.State.PLANNED, "approve"): UpgradeJournal.State.APPROVED,
        (UpgradeJournal.State.APPROVED, "start"): UpgradeJournal.State.RUNNING,
        (UpgradeJournal.State.RUNNING, "begin-verification"): UpgradeJournal.State.VERIFYING,
        (UpgradeJournal.State.VERIFYING, "complete"): UpgradeJournal.State.COMPLETED,
        (UpgradeJournal.State.RUNNING, "fail"): UpgradeJournal.State.FAILED,
        (UpgradeJournal.State.VERIFYING, "fail"): UpgradeJournal.State.FAILED,
        (UpgradeJournal.State.FAILED, "stage-rollback"): UpgradeJournal.State.ROLLBACK_STAGED,
    }
    target = transitions.get((journal.state, action))
    if not target:
        raise ValueError(f"invalid upgrade transition: {journal.state} -> {action}")
    if action == "approve" and (not journal.preflight.get("ready") or not journal.backup_id):
        raise ValueError("upgrade approval requires passed preflight and verified backup")
    if action == "start":
        if not MaintenanceState.objects.filter(pk=1, active=True, read_only=True).exists():
            raise ValueError("maintenance read-only mode is required before upgrade start")
        journal.started_at = timezone.now()
    if action == "complete":
        required = {
            "migrations_match", "django_checks_pass", "storage_healthy",
            "backup_catalog_readable", "authentication_works",
        }
        supplied = verification or {}
        missing = sorted(key for key in required if supplied.get(key) is not True)
        if missing:
            raise ValueError(f"post-upgrade verification failed: {', '.join(missing)}")
        journal.verification = supplied
        journal.finished_at = timezone.now()
    if action == "fail":
        journal.failure_code = str((verification or {}).get("failure_code", "operator-reported"))[:100]
        journal.finished_at = timezone.now()
    journal.state = target
    journal.save()
    membership = actor.wagvid_memberships.filter(active=True).first()
    if membership:
        membership.organization.audit_events.create(
            actor=actor,
            action=f"system.upgrade-{action}",
            object_type="upgrade-journal",
            object_id=str(journal.id),
            metadata={"state": target, "backup_id": str(journal.backup_id or "")},
        )
    return journal
