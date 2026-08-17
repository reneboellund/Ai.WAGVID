"""Provider-neutral shared-file storage contract for GPU/media workers.

Azure NetApp Files and Google Cloud NetApp Volumes are file services, while FSx ONTAP
and CVO may expose both file and object paths. This contract keeps NFS/SMB mount
identity separate from S3 object identity and never places cloud credentials in jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class SharedFileProtocol(StrEnum):
    NFS = "nfs"
    SMB = "smb"


class SharedFileFeature(StrEnum):
    READ = "read"
    WRITE = "write"
    SNAPSHOT = "snapshot"
    CLONE = "clone"
    BACKUP = "backup"
    CROSS_REGION_REPLICATION = "cross-region-replication"
    FILE_RESTORE = "file-restore"
    VOLUME_REVERT = "volume-revert"


@dataclass(frozen=True)
class SharedFileCapabilities:
    protocols: frozenset[SharedFileProtocol]
    features: frozenset[SharedFileFeature]
    private_network_required: bool = True
    max_volume_bytes: int | None = None
    notes: tuple[str, ...] = ()

    def supports(self, feature: SharedFileFeature) -> bool:
        return feature in self.features


@dataclass(frozen=True)
class SharedFileResource:
    provider_id: str
    resource_id: str
    provider_type: str
    cloud_provider: str
    region: str
    account_scope: str
    protocol: SharedFileProtocol
    mount_reference: str
    capacity_bytes: int | None
    capabilities: SharedFileCapabilities
    network_scope: str | None = None
    service_level: str | None = None
    throughput_mibps: float | None = None
    iops: int | None = None
    health: str = "unknown"
    read_only: bool = False

    def __post_init__(self) -> None:
        if not self.provider_id or not self.resource_id or not self.mount_reference:
            raise ValueError("provider_id, resource_id and mount_reference are required")
        if self.protocol not in self.capabilities.protocols:
            raise ValueError("Resource protocol is not advertised by provider capabilities")
        if self.capacity_bytes is not None and self.capacity_bytes < 0:
            raise ValueError("capacity_bytes cannot be negative")

    @property
    def canonical_file_identity_prefix(self) -> str:
        return f"file://{self.provider_id}/{self.resource_id}"

    @property
    def locality_token(self) -> str:
        return f"file:{self.provider_type}:{self.cloud_provider}:{self.region}:{self.resource_id}"


@dataclass(frozen=True)
class SharedFileLocation:
    provider_id: str
    resource_id: str
    relative_path: str

    def __post_init__(self) -> None:
        path = self.relative_path.replace("\\", "/").strip("/")
        if not path or ".." in path.split("/"):
            raise ValueError("Unsafe shared-file relative path")
        object.__setattr__(self, "relative_path", path)

    @property
    def canonical_identity(self) -> str:
        return f"file://{self.provider_id}/{self.resource_id}/{self.relative_path}"


@dataclass(frozen=True)
class WorkerMountContext:
    worker_id: str
    cloud_provider: str
    region: str
    network_scopes: frozenset[str]
    identity_ref: str | None = None


@dataclass(frozen=True)
class MountPlan:
    resource: SharedFileResource
    worker_id: str
    mount_reference: str
    protocol: SharedFileProtocol
    read_only: bool
    identity_ref: str | None
    locality_token: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SharedFilePreflight:
    usable: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def plan_worker_mount(
    resource: SharedFileResource,
    worker: WorkerMountContext,
    *,
    require_write: bool = False,
    require_same_region: bool = True,
) -> tuple[SharedFilePreflight, MountPlan | None]:
    blockers: list[str] = []
    warnings: list[str] = []
    healthy_states = {"available", "ready", "healthy", "online", "running", "succeeded", "active"}
    if resource.health.casefold() not in healthy_states:
        blockers.append(f"resource-health:{resource.health}")
    if require_write and (
        resource.read_only or SharedFileFeature.WRITE not in resource.capabilities.features
    ):
        blockers.append("write-required-but-unavailable")
    if SharedFileFeature.READ not in resource.capabilities.features:
        blockers.append("read-capability-unavailable")
    if require_same_region and worker.region != resource.region:
        blockers.append(f"cross-region-mount-rejected:worker={worker.region}:storage={resource.region}")
    elif worker.region != resource.region:
        warnings.append(f"cross-region-data-path:worker={worker.region}:storage={resource.region}")
    if worker.cloud_provider != resource.cloud_provider:
        warnings.append(f"cross-cloud-data-path:worker={worker.cloud_provider}:storage={resource.cloud_provider}")
    if resource.capabilities.private_network_required:
        if not resource.network_scope:
            blockers.append("private-network-scope-missing")
        elif resource.network_scope not in worker.network_scopes:
            blockers.append("worker-not-in-authorized-storage-network")
    if resource.protocol == SharedFileProtocol.SMB and not worker.identity_ref:
        blockers.append("smb-worker-identity-required")

    if blockers:
        return SharedFilePreflight(False, tuple(blockers), tuple(warnings)), None
    return (
        SharedFilePreflight(True, (), tuple(warnings)),
        MountPlan(
            resource=resource,
            worker_id=worker.worker_id,
            mount_reference=resource.mount_reference,
            protocol=resource.protocol,
            read_only=resource.read_only or not require_write,
            identity_ref=worker.identity_ref,
            locality_token=resource.locality_token,
            warnings=tuple(warnings),
        ),
    )


class SharedFileProvider(Protocol):
    provider_id: str
    def resources(self) -> tuple[SharedFileResource, ...]: ...
    def preflight(self, resource_id: str) -> SharedFilePreflight: ...
