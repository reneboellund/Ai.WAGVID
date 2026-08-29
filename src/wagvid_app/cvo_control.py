"""Cloud Volumes ONTAP working-environment and ONTAP handoff contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .netapp_cloud import NetAppCloudService
from .netapp_cloud_control import NetAppCloudAction, NetAppCloudOperation, NetAppCloudPlan


class CvoTopology(StrEnum):
    SINGLE_NODE = "single-node"
    HA = "ha"


@dataclass(frozen=True)
class CvoWorkingEnvironment:
    provider_id: str
    working_environment_id: str
    name: str
    cloud_provider: str
    region: str
    topology: CvoTopology
    ontap_version: str
    status: str
    account_scope: str
    network_scope: str | None
    capacity_bytes: int | None
    license_summary: str | None = None
    tiering_summary: str | None = None
    ontap_management_endpoint_ref: str | None = None
    ontap_s3_endpoint_ref: str | None = None

    @property
    def locality_token(self) -> str:
        return f"netapp:cvo:{self.cloud_provider}:{self.region}:{self.working_environment_id}"


@dataclass(frozen=True)
class OntapHandoff:
    provider_id: str
    working_environment_id: str
    ontap_version: str
    management_endpoint_ref: str
    management_credential_ref: str
    s3_endpoint_ref: str | None
    network_scope: str | None

    def __post_init__(self) -> None:
        if not self.management_endpoint_ref.startswith(("https://", "secret://", "config://")):
            raise ValueError("ONTAP management endpoint must be a safe config/reference")
        if not self.management_credential_ref.startswith("secret://"):
            raise ValueError("ONTAP management credentials must be a secret reference")


class CvoConsoleApi(Protocol):
    def discover_working_environments(self) -> tuple[Mapping[str, object], ...]: ...
    def execute(
        self, operation: str, *, working_environment_id: str,
        details: Mapping[str, object], idempotency_key: str,
    ) -> str: ...


def normalize_cvo_environment(
    record: Mapping[str, object], *, provider_id: str, cloud_provider: str, account_scope: str,
) -> CvoWorkingEnvironment:
    environment_id = str(record.get("id") or record.get("working_environment_id") or "").strip()
    if not environment_id:
        raise ValueError("CVO working environment id is required")
    region = str(record.get("region") or "").strip()
    if not region:
        raise ValueError("CVO region is required")
    topology_value = str(record.get("topology") or "single-node").casefold()
    topology = CvoTopology.HA if topology_value in {"ha", "high-availability"} else CvoTopology.SINGLE_NODE
    capacity = record.get("capacity_bytes")
    capacity_bytes = int(capacity) if capacity is not None else None
    if capacity_bytes is not None and capacity_bytes < 0:
        raise ValueError("CVO capacity cannot be negative")
    return CvoWorkingEnvironment(
        provider_id=provider_id,
        working_environment_id=environment_id,
        name=str(record.get("name") or environment_id),
        cloud_provider=cloud_provider,
        region=region,
        topology=topology,
        ontap_version=str(record.get("ontap_version") or "unknown"),
        status=str(record.get("status") or "unknown").casefold(),
        account_scope=account_scope,
        network_scope=str(record.get("network_scope") or "") or None,
        capacity_bytes=capacity_bytes,
        license_summary=str(record.get("license_summary") or "") or None,
        tiering_summary=str(record.get("tiering_summary") or "") or None,
        ontap_management_endpoint_ref=str(record.get("ontap_management_endpoint_ref") or "") or None,
        ontap_s3_endpoint_ref=str(record.get("ontap_s3_endpoint_ref") or "") or None,
    )


def build_ontap_handoff(
    environment: CvoWorkingEnvironment, *, management_credential_ref: str,
) -> OntapHandoff:
    if environment.status not in {"running", "online", "available", "ready"}:
        raise ValueError(f"CVO working environment is not reachable: {environment.status}")
    if not environment.ontap_management_endpoint_ref:
        raise ValueError("CVO discovery did not provide an ONTAP management endpoint reference")
    return OntapHandoff(
        provider_id=environment.provider_id,
        working_environment_id=environment.working_environment_id,
        ontap_version=environment.ontap_version,
        management_endpoint_ref=environment.ontap_management_endpoint_ref,
        management_credential_ref=management_credential_ref,
        s3_endpoint_ref=environment.ontap_s3_endpoint_ref,
        network_scope=environment.network_scope,
    )


def plan_cvo_power_action(environment: CvoWorkingEnvironment, *, start: bool) -> NetAppCloudPlan:
    operation = NetAppCloudOperation.START_SYSTEM if start else NetAppCloudOperation.STOP_SYSTEM
    running_states = {"running", "online", "available", "ready"}
    if start and environment.status in running_states:
        return NetAppCloudPlan((), warnings=("cvo-already-running",))
    if not start and environment.status == "stopped":
        return NetAppCloudPlan((), warnings=("cvo-already-stopped",))
    target_state = "running" if start else "stopped"
    return NetAppCloudPlan(
        actions=(
            NetAppCloudAction(
                operation,
                environment.provider_id,
                environment.working_environment_id,
                NetAppCloudService.CLOUD_VOLUMES_ONTAP,
                {"target_state": target_state},
            ),
        )
    )


def validate_cvo_cloud_mutation(operation: str) -> None:
    forbidden = {
        "create-cloud-disk", "delete-cloud-disk", "resize-cloud-disk",
        "create-aggregate-direct", "delete-aggregate-direct",
    }
    if operation in forbidden:
        raise ValueError("CVO cloud capacity must be managed through NetApp Console-supported operations")
