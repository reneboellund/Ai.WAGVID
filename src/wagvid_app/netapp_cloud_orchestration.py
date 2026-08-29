"""Idempotent NetApp cloud lifecycle/protection orchestration over provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from .netapp_cloud import NetAppCloudResource, NetAppCloudService
from .netapp_cloud_control import (
    NetAppCloudAction,
    NetAppCloudApproval,
    NetAppCloudOperation,
    NetAppCloudPlan,
    validate_action_for_resource,
    validate_approval,
)
from .shared_file_provider import SharedFileProtocol


@dataclass(frozen=True)
class DesiredCloudVolume:
    provider_id: str
    resource_id: str
    service: NetAppCloudService
    cloud_provider: str
    region: str
    account_scope: str
    capacity_bytes: int
    protocol: SharedFileProtocol
    network_scope: str
    service_level: str | None = None

    def __post_init__(self) -> None:
        if self.capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        if not all((self.provider_id, self.resource_id, self.cloud_provider, self.region, self.account_scope, self.network_scope)):
            raise ValueError("Desired cloud volume identity fields are required")


@dataclass(frozen=True)
class AppliedCloudAction:
    action: NetAppCloudAction
    provider_operation_id: str


class NetAppCloudMutationApi(Protocol):
    def execute(
        self, operation: NetAppCloudOperation, *, resource_id: str,
        details: Mapping[str, object], idempotency_key: str,
    ) -> str: ...


def plan_volume_reconciliation(
    desired: DesiredCloudVolume,
    current: NetAppCloudResource | None,
) -> NetAppCloudPlan:
    if current is None:
        return NetAppCloudPlan(
            actions=(
                NetAppCloudAction(
                    NetAppCloudOperation.CREATE_VOLUME,
                    desired.provider_id,
                    desired.resource_id,
                    desired.service,
                    {
                        "cloud_provider": desired.cloud_provider,
                        "region": desired.region,
                        "account_scope": desired.account_scope,
                        "capacity_bytes": desired.capacity_bytes,
                        "protocol": desired.protocol.value,
                        "network_scope": desired.network_scope,
                        "service_level": desired.service_level,
                    },
                ),
            )
        )

    blockers: list[str] = []
    warnings: list[str] = []
    actions: list[NetAppCloudAction] = []
    if current.service != desired.service:
        blockers.append("existing-resource-service-mismatch")
    if current.region != desired.region:
        blockers.append("in-place-region-change-not-supported")
    if current.account_scope != desired.account_scope:
        blockers.append("in-place-account-scope-change-not-supported")
    if current.capacity_bytes is not None and desired.capacity_bytes < current.capacity_bytes:
        blockers.append("automatic-volume-shrink-rejected")
    if current.capacity_bytes is None:
        warnings.append("current-capacity-unknown")
    changes: dict[str, object] = {}
    if current.capacity_bytes != desired.capacity_bytes:
        changes["capacity_bytes"] = desired.capacity_bytes
    if desired.service_level and current.service_level != desired.service_level:
        changes["service_level"] = desired.service_level
    if current.network_scope != desired.network_scope:
        blockers.append("network-scope-change-requires-separate-connectivity-plan")
    if changes and not blockers:
        actions.append(
            NetAppCloudAction(
                NetAppCloudOperation.UPDATE_VOLUME,
                desired.provider_id,
                current.resource_id,
                current.service,
                changes,
            )
        )
    return NetAppCloudPlan(tuple(actions), tuple(warnings), tuple(blockers))


def plan_snapshot(
    resource: NetAppCloudResource, *, provider_id: str, snapshot_name: str, reason: str,
) -> NetAppCloudPlan:
    if not snapshot_name or not reason:
        raise ValueError("snapshot_name and reason are required")
    action = NetAppCloudAction(
        NetAppCloudOperation.CREATE_SNAPSHOT,
        provider_id,
        resource.resource_id,
        resource.service,
        {"snapshot_name": snapshot_name, "reason": reason},
    )
    return NetAppCloudPlan((action,), blockers=validate_action_for_resource(action, resource))


def plan_replication_action(
    resource: NetAppCloudResource,
    *,
    provider_id: str,
    operation: NetAppCloudOperation,
    destination_region: str | None = None,
    relationship_id: str | None = None,
) -> NetAppCloudPlan:
    allowed = {
        NetAppCloudOperation.CREATE_REPLICATION,
        NetAppCloudOperation.SYNC_REPLICATION,
        NetAppCloudOperation.STOP_REPLICATION,
        NetAppCloudOperation.RESUME_REPLICATION,
        NetAppCloudOperation.BREAK_REPLICATION,
        NetAppCloudOperation.RESYNC_REPLICATION,
        NetAppCloudOperation.REVERSE_REPLICATION,
    }
    if operation not in allowed:
        raise ValueError("Unsupported replication operation")
    details: dict[str, object] = {}
    if destination_region:
        details["destination_region"] = destination_region
    if relationship_id:
        details["relationship_id"] = relationship_id
    blockers: list[str] = []
    if operation == NetAppCloudOperation.CREATE_REPLICATION and not destination_region:
        blockers.append("destination-region-required")
    if operation != NetAppCloudOperation.CREATE_REPLICATION and not relationship_id:
        blockers.append("relationship-id-required")
    action = NetAppCloudAction(
        operation,
        provider_id,
        resource.resource_id,
        resource.service,
        details,
        destructive=operation in {
            NetAppCloudOperation.BREAK_REPLICATION,
            NetAppCloudOperation.RESYNC_REPLICATION,
            NetAppCloudOperation.REVERSE_REPLICATION,
        },
    )
    blockers.extend(validate_action_for_resource(action, resource))
    return NetAppCloudPlan((action,), blockers=tuple(dict.fromkeys(blockers)))


def plan_fsx_s3_access_point(
    resource: NetAppCloudResource,
    *,
    provider_id: str,
    access_point_id: str,
    directory_path: str,
    requested_features: frozenset[str] = frozenset(),
) -> NetAppCloudPlan:
    if resource.service != NetAppCloudService.FSX_ONTAP:
        return NetAppCloudPlan((), blockers=("fsx-resource-required",))
    unsupported = sorted(requested_features.intersection({"presigned-url", "versioning", "object-lock", "lifecycle"}))
    blockers = tuple(f"fsx-s3-access-point-unsupported:{item}" for item in unsupported)
    path = directory_path.replace("\\", "/").strip()
    if not path.startswith("/") or ".." in path.split("/"):
        blockers += ("unsafe-fsx-access-point-directory",)
    action = NetAppCloudAction(
        NetAppCloudOperation.CREATE_S3_ACCESS_POINT,
        provider_id,
        resource.resource_id,
        resource.service,
        {
            "access_point_id": access_point_id,
            "directory_path": path,
            "max_object_size_bytes": 50 * 1024**3,
            "presigned_urls": False,
            "versioning": False,
            "object_lock": False,
            "lifecycle": False,
        },
    )
    return NetAppCloudPlan((action,), blockers=tuple(dict.fromkeys(blockers)))


def apply_plan(
    plan: NetAppCloudPlan,
    approval: NetAppCloudApproval,
    *,
    api: NetAppCloudMutationApi,
    now: datetime,
) -> tuple[AppliedCloudAction, ...]:
    validate_approval(plan, approval, now=now)
    applied: list[AppliedCloudAction] = []
    for index, action in enumerate(plan.actions):
        operation_id = api.execute(
            action.operation,
            resource_id=action.resource_id,
            details=action.details,
            idempotency_key=f"{plan.digest}:{index}",
        )
        if not operation_id:
            raise RuntimeError("Provider mutation did not return an operation identifier")
        applied.append(AppliedCloudAction(action, operation_id))
    return tuple(applied)
