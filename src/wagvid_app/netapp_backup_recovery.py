"""NetApp Console Backup & Recovery integration contracts.

Backup is protection metadata/control plane and never the live object/file provider.
Restore defaults to an alternate target and cannot change canonical routing without a
separate integrity-validated cutover.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .netapp_cloud import NetAppCloudResource, ProtectionFeature
from .netapp_cloud_control import (
    NetAppCloudAction,
    NetAppCloudOperation,
    NetAppCloudPlan,
    ProtectionState,
    RecoveryPoint,
    RestorePlan,
    staged_restore_plan,
    validate_restore_cutover,
)


class BackupJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class BackupPolicy:
    policy_id: str
    name: str
    retention_summary: str
    destination_summary: str
    schedule_summary: str | None = None
    immutable: bool | None = None


@dataclass(frozen=True)
class BackupRoleMapping:
    logical_role: str
    provider_id: str
    resource_id: str
    policy_id: str

    def __post_init__(self) -> None:
        if self.logical_role not in {"originals", "metadata", "results", "audit", "backup"}:
            raise ValueError("Backup policy mapping is only valid for retained/protected roles")


@dataclass(frozen=True)
class BackupJob:
    job_id: str
    provider_id: str
    resource_id: str
    state: BackupJobState
    started_at: datetime | None = None
    completed_at: datetime | None = None
    recovery_point_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BackupReadiness:
    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


class NetAppBackupRecoveryApi(Protocol):
    def policies(self) -> tuple[BackupPolicy, ...]: ...
    def protection_state(self, resource_id: str) -> ProtectionState: ...
    def recovery_points(self, resource_id: str) -> tuple[RecoveryPoint, ...]: ...
    def jobs(self, resource_id: str) -> tuple[BackupJob, ...]: ...
    def execute(
        self, operation: str, *, resource_id: str,
        details: Mapping[str, object], idempotency_key: str,
    ) -> str: ...


def plan_backup_policy_mapping(
    resource: NetAppCloudResource,
    *,
    provider_id: str,
    logical_role: str,
    policy: BackupPolicy,
) -> tuple[BackupRoleMapping, NetAppCloudPlan]:
    blockers: list[str] = []
    if ProtectionFeature.BACKUP not in resource.capabilities.protection:
        blockers.append("backup-feature-unavailable")
    if logical_role not in {"originals", "metadata", "results", "audit", "backup"}:
        blockers.append("logical-role-not-eligible-for-managed-backup")
    mapping = BackupRoleMapping(logical_role, provider_id, resource.resource_id, policy.policy_id)
    action = NetAppCloudAction(
        NetAppCloudOperation.ENABLE_BACKUP,
        provider_id,
        resource.resource_id,
        resource.service,
        {
            "policy_id": policy.policy_id,
            "logical_role": logical_role,
            "retention_summary": policy.retention_summary,
            "destination_summary": policy.destination_summary,
        },
    )
    return mapping, NetAppCloudPlan((action,), blockers=tuple(blockers))


def backup_readiness(protection: ProtectionState, jobs: tuple[BackupJob, ...]) -> BackupReadiness:
    blockers: list[str] = []
    warnings: list[str] = []
    if not protection.enabled:
        blockers.append("backup-protection-disabled")
    if protection.health not in {"healthy", "available", "ready"}:
        blockers.append(f"backup-protection-health:{protection.health}")
    latest = jobs[0] if jobs else None
    if latest is None:
        warnings.append("no-backup-job-history")
    elif latest.state == BackupJobState.FAILED:
        blockers.append(f"latest-backup-failed:{latest.error_code or 'unknown'}")
    elif latest.state == BackupJobState.DEGRADED:
        warnings.append(f"latest-backup-degraded:{latest.error_code or 'unknown'}")
    return BackupReadiness(not blockers, tuple(blockers), tuple(warnings))


def plan_backup_restore(
    recovery_point: RecoveryPoint,
    *,
    alternate_target: str,
    canonical_route_unchanged: bool = True,
) -> RestorePlan:
    if recovery_point.feature != ProtectionFeature.BACKUP:
        raise ValueError("Recovery point is not a NetApp Backup & Recovery point")
    return staged_restore_plan(
        recovery_point,
        staging_target=alternate_target,
        canonical_route_unchanged=canonical_route_unchanged,
    )


def validate_backup_restore_cutover(
    plan: RestorePlan,
    *,
    restored_sha256: str | None,
    object_or_file_inventory_verified: bool,
    target_provider_healthy: bool,
    canonical_routing_still_unchanged: bool,
    confirmation: str | None,
) -> tuple[str, ...]:
    blockers = list(
        validate_restore_cutover(
            plan,
            restored_sha256=restored_sha256,
            inventory_verified=object_or_file_inventory_verified,
            provider_healthy=target_provider_healthy,
            confirmation=confirmation,
        )
    )
    if not canonical_routing_still_unchanged:
        blockers.append("canonical-routing-changed-before-restore-validation")
    return tuple(dict.fromkeys(blockers))
