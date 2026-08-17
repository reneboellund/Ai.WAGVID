"""NetApp cloud control/protection planning and approval contracts.

Provider SDK/REST adapters translate their discovery into these records. Planning is pure
and ordinary CI never creates cloud resources, snapshots, mirrors, backups or restores.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, Protocol

from .netapp_cloud import NetAppCloudResource, NetAppCloudService, ProtectionFeature


class NetAppCloudOperation(StrEnum):
    CREATE_VOLUME = "create-volume"
    UPDATE_VOLUME = "update-volume"
    CREATE_SNAPSHOT = "create-snapshot"
    DELETE_SNAPSHOT = "delete-snapshot"
    FILE_RESTORE = "file-restore"
    VOLUME_REVERT = "volume-revert"
    ENABLE_BACKUP = "enable-backup"
    RUN_BACKUP = "run-backup"
    RESTORE_BACKUP = "restore-backup"
    CREATE_REPLICATION = "create-replication"
    SYNC_REPLICATION = "sync-replication"
    STOP_REPLICATION = "stop-replication"
    RESUME_REPLICATION = "resume-replication"
    BREAK_REPLICATION = "break-replication"
    RESYNC_REPLICATION = "resync-replication"
    REVERSE_REPLICATION = "reverse-replication"
    START_SYSTEM = "start-system"
    STOP_SYSTEM = "stop-system"
    CREATE_S3_ACCESS_POINT = "create-s3-access-point"
    DELETE_S3_ACCESS_POINT = "delete-s3-access-point"


REPLICATION_OPERATIONS = frozenset(
    {
        NetAppCloudOperation.CREATE_REPLICATION,
        NetAppCloudOperation.SYNC_REPLICATION,
        NetAppCloudOperation.STOP_REPLICATION,
        NetAppCloudOperation.RESUME_REPLICATION,
        NetAppCloudOperation.BREAK_REPLICATION,
        NetAppCloudOperation.RESYNC_REPLICATION,
        NetAppCloudOperation.REVERSE_REPLICATION,
    }
)

DESTRUCTIVE_OPERATIONS = frozenset(
    {
        NetAppCloudOperation.DELETE_SNAPSHOT,
        NetAppCloudOperation.VOLUME_REVERT,
        NetAppCloudOperation.BREAK_REPLICATION,
        NetAppCloudOperation.RESYNC_REPLICATION,
        NetAppCloudOperation.REVERSE_REPLICATION,
        NetAppCloudOperation.DELETE_S3_ACCESS_POINT,
    }
)


@dataclass(frozen=True)
class NetAppCloudAction:
    operation: NetAppCloudOperation
    provider_id: str
    resource_id: str
    service: NetAppCloudService
    details: Mapping[str, object]
    destructive: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or not self.resource_id:
            raise ValueError("provider_id and resource_id are required")
        if self.operation in DESTRUCTIVE_OPERATIONS and not self.destructive:
            raise ValueError(f"{self.operation.value} must be marked destructive")
        _reject_secret_material(self.details)


@dataclass(frozen=True)
class NetAppCloudPlan:
    actions: tuple[NetAppCloudAction, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def applicable(self) -> bool:
        return not self.blockers

    @property
    def has_destructive_actions(self) -> bool:
        return any(action.destructive for action in self.actions)

    @property
    def digest(self) -> str:
        payload = {
            "actions": [
                {
                    "operation": action.operation.value,
                    "provider_id": action.provider_id,
                    "resource_id": action.resource_id,
                    "service": action.service.value,
                    "details": dict(action.details),
                    "destructive": action.destructive,
                }
                for action in self.actions
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class NetAppCloudApproval:
    plan_digest: str
    approved_by: str
    approved_at: datetime
    expires_at: datetime
    confirmation: str

    def __post_init__(self) -> None:
        if not self.plan_digest or not self.approved_by:
            raise ValueError("plan_digest and approved_by are required")
        if any(value.tzinfo is None or value.utcoffset() is None for value in (self.approved_at, self.expires_at)):
            raise ValueError("Approval timestamps must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("Approval expiry must follow approval time")


@dataclass(frozen=True)
class ProtectionState:
    provider_id: str
    resource_id: str
    feature: ProtectionFeature
    enabled: bool
    health: str
    last_success_at: datetime | None = None
    next_scheduled_at: datetime | None = None
    recovery_points: int | None = None
    destination_summary: str | None = None
    lag_seconds: int | None = None
    provider_reference: str | None = None


@dataclass(frozen=True)
class RecoveryPoint:
    provider_id: str
    resource_id: str
    recovery_point_id: str
    feature: ProtectionFeature
    created_at: datetime
    source_hash: str | None = None
    destination_summary: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Recovery point timestamp must be timezone-aware")


@dataclass(frozen=True)
class RestorePlan:
    provider_id: str
    resource_id: str
    recovery_point_id: str
    restore_target: str
    staging: bool
    expected_sha256: str | None
    steps: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    @property
    def cutover_allowed(self) -> bool:
        return not self.blockers and self.staging


class NetAppCloudControl(Protocol):
    provider_id: str
    def discover(self) -> tuple[NetAppCloudResource, ...]: ...
    def protection_state(self, resource_id: str) -> tuple[ProtectionState, ...]: ...
    def apply(self, action: NetAppCloudAction) -> str: ...


def _reject_secret_material(value: object, *, path: str = "details") -> None:
    sensitive = {
        "password", "secret", "secret_key", "access_key", "access_key_id",
        "token", "client_secret", "service_account_key",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).casefold()
            if key_text in sensitive or key_text.endswith("_password") or key_text.endswith("_secret"):
                raise ValueError(f"Secret material is not allowed in cloud action plans: {path}.{key}")
            _reject_secret_material(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_secret_material(item, path=f"{path}[{index}]")


def validate_approval(plan: NetAppCloudPlan, approval: NetAppCloudApproval, *, now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not plan.applicable:
        raise ValueError("Blocked NetApp cloud plan cannot be applied")
    if approval.plan_digest != plan.digest:
        raise ValueError("NetApp cloud plan changed after approval")
    if now.astimezone(UTC) > approval.expires_at.astimezone(UTC):
        raise ValueError("NetApp cloud approval expired")
    required = (
        "APPLY DESTRUCTIVE NETAPP PROTECTION CHANGE"
        if plan.has_destructive_actions
        else "APPLY NETAPP CLOUD CHANGES"
    )
    if approval.confirmation != required:
        raise ValueError(f"Explicit confirmation required: {required}")


def required_protection_feature(
    operation: NetAppCloudOperation,
    *,
    service: NetAppCloudService | None = None,
) -> ProtectionFeature | None:
    if operation in {
        NetAppCloudOperation.CREATE_SNAPSHOT,
        NetAppCloudOperation.DELETE_SNAPSHOT,
        NetAppCloudOperation.VOLUME_REVERT,
        NetAppCloudOperation.FILE_RESTORE,
    }:
        return ProtectionFeature.SNAPSHOT
    if operation in {
        NetAppCloudOperation.ENABLE_BACKUP,
        NetAppCloudOperation.RUN_BACKUP,
        NetAppCloudOperation.RESTORE_BACKUP,
    }:
        return ProtectionFeature.BACKUP
    if operation in REPLICATION_OPERATIONS:
        if service in {NetAppCloudService.CLOUD_VOLUMES_ONTAP, NetAppCloudService.FSX_ONTAP}:
            return ProtectionFeature.SNAPMIRROR
        return ProtectionFeature.CROSS_REGION_REPLICATION
    return None


def validate_action_for_resource(action: NetAppCloudAction, resource: NetAppCloudResource) -> tuple[str, ...]:
    blockers: list[str] = []
    if action.resource_id != resource.resource_id:
        blockers.append("action-resource-mismatch")
    if action.service != resource.service:
        blockers.append("action-service-mismatch")
    if resource.health not in {"available", "ready", "healthy", "online", "running", "stopped"}:
        blockers.append(f"resource-health:{resource.health}")
    required = required_protection_feature(action.operation, service=resource.service)
    if required is not None and required not in resource.capabilities.protection:
        blockers.append(f"protection-feature-unavailable:{required.value}")
    return tuple(blockers)


def staged_restore_plan(
    recovery_point: RecoveryPoint,
    *,
    staging_target: str,
    canonical_route_unchanged: bool,
) -> RestorePlan:
    blockers: list[str] = []
    if not staging_target:
        blockers.append("staging-target-required")
    if not canonical_route_unchanged:
        blockers.append("restore-must-not-rewrite-canonical-routing")
    return RestorePlan(
        provider_id=recovery_point.provider_id,
        resource_id=recovery_point.resource_id,
        recovery_point_id=recovery_point.recovery_point_id,
        restore_target=staging_target,
        staging=True,
        expected_sha256=recovery_point.source_hash,
        steps=(
            "restore provider recovery point to alternate/staging target",
            "rebuild or read restored object/file inventory",
            "validate canonical Ai.WAGVID SHA-256/provenance",
            "compare protected source and restored target identities",
            "require separate production routing cutover approval",
        ),
        blockers=tuple(blockers),
    )


def validate_restore_cutover(
    plan: RestorePlan,
    *,
    restored_sha256: str | None,
    inventory_verified: bool,
    provider_healthy: bool,
    confirmation: str | None,
) -> tuple[str, ...]:
    blockers = list(plan.blockers)
    if not inventory_verified:
        blockers.append("restored-inventory-not-verified")
    if not provider_healthy:
        blockers.append("restore-target-provider-unhealthy")
    if plan.expected_sha256 is not None and restored_sha256 != plan.expected_sha256:
        blockers.append("restored-sha256-mismatch")
    if confirmation != "CUT OVER VERIFIED NETAPP RESTORE":
        blockers.append("explicit-restore-cutover-confirmation-required")
    return tuple(dict.fromkeys(blockers))
