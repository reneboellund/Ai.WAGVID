"""NetApp cloud/shared-file capability contracts.

FSx for ONTAP, Azure NetApp Files, Google Cloud NetApp Volumes and Cloud Volumes
ONTAP are peers with different control planes. This module records what an attached
resource can actually do and supplies locality/protection hints without replacing the
provider-neutral object-storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NetAppCloudService(StrEnum):
    FSX_ONTAP = "fsx-ontap"
    AZURE_NETAPP_FILES = "azure-netapp-files"
    GOOGLE_CLOUD_NETAPP_VOLUMES = "google-cloud-netapp-volumes"
    CLOUD_VOLUMES_ONTAP = "cloud-volumes-ontap"


class FileProtocol(StrEnum):
    NFS = "nfs"
    SMB = "smb"
    ISCSI = "iscsi"
    S3_ACCESS_POINT = "s3-access-point"
    ONTAP_S3 = "ontap-s3"


class ProtectionFeature(StrEnum):
    SNAPSHOT = "snapshot"
    CROSS_REGION_REPLICATION = "cross-region-replication"
    SNAPMIRROR = "snapmirror"
    BACKUP = "backup"
    CLONE = "clone"


@dataclass(frozen=True)
class NetAppCloudCapabilities:
    protocols: frozenset[FileProtocol]
    protection: frozenset[ProtectionFeature]
    ontap_rest: bool = False
    s3_presigned_urls: bool = False
    s3_versioning: bool = False
    s3_object_lock: bool = False
    s3_lifecycle: bool = False
    s3_max_object_size_bytes: int | None = None


@dataclass(frozen=True)
class NetAppCloudResource:
    resource_id: str
    service: NetAppCloudService
    cloud_provider: str
    region: str
    account_scope: str
    capacity_bytes: int | None
    capabilities: NetAppCloudCapabilities
    network_scope: str | None = None
    service_level: str | None = None
    health: str = "unknown"
    mount_reference: str | None = None
    s3_endpoint_reference: str | None = None

    @property
    def locality_token(self) -> str:
        return f"netapp:{self.service.value}:{self.cloud_provider}:{self.region}:{self.resource_id}"


@dataclass(frozen=True)
class ProtectionRecommendation:
    feature: ProtectionFeature
    priority: str
    reason: str


def fsx_ontap_s3_access_point_capabilities() -> NetAppCloudCapabilities:
    """Documented FSx ONTAP S3 Access Point capability boundary.

    The S3 access path is useful for object-style access to file data but is not an AWS
    S3 bucket and must not satisfy governance requirements it does not implement.
    """
    return NetAppCloudCapabilities(
        protocols=frozenset({FileProtocol.NFS, FileProtocol.SMB, FileProtocol.S3_ACCESS_POINT}),
        protection=frozenset({ProtectionFeature.SNAPSHOT, ProtectionFeature.BACKUP}),
        ontap_rest=True,
        s3_presigned_urls=False,
        s3_versioning=False,
        s3_object_lock=False,
        s3_lifecycle=False,
        s3_max_object_size_bytes=50 * 1024**3,
    )


def azure_netapp_files_capabilities() -> NetAppCloudCapabilities:
    return NetAppCloudCapabilities(
        protocols=frozenset({FileProtocol.NFS, FileProtocol.SMB}),
        protection=frozenset(
            {
                ProtectionFeature.SNAPSHOT,
                ProtectionFeature.CROSS_REGION_REPLICATION,
                ProtectionFeature.BACKUP,
            }
        ),
    )


def google_cloud_netapp_volumes_capabilities() -> NetAppCloudCapabilities:
    return NetAppCloudCapabilities(
        protocols=frozenset({FileProtocol.NFS, FileProtocol.SMB}),
        protection=frozenset(
            {ProtectionFeature.SNAPSHOT, ProtectionFeature.CROSS_REGION_REPLICATION}
        ),
    )


def cloud_volumes_ontap_capabilities(*, s3_enabled: bool = True) -> NetAppCloudCapabilities:
    protocols = {FileProtocol.NFS, FileProtocol.SMB, FileProtocol.ISCSI}
    if s3_enabled:
        protocols.add(FileProtocol.ONTAP_S3)
    return NetAppCloudCapabilities(
        protocols=frozenset(protocols),
        protection=frozenset(
            {ProtectionFeature.SNAPSHOT, ProtectionFeature.SNAPMIRROR, ProtectionFeature.BACKUP}
        ),
        ontap_rest=True,
    )


def protection_recommendations(
    resource: NetAppCloudResource, *, logical_role: str
) -> tuple[ProtectionRecommendation, ...]:
    """Return advisory recommendations; no protection mutation is automatic."""
    available = resource.capabilities.protection
    recommendations: list[ProtectionRecommendation] = []
    if logical_role in {"originals", "audit", "backup"}:
        if ProtectionFeature.CROSS_REGION_REPLICATION in available:
            recommendations.append(
                ProtectionRecommendation(
                    ProtectionFeature.CROSS_REGION_REPLICATION,
                    "high",
                    "Retained evidence benefits from a second-region recovery copy",
                )
            )
        elif ProtectionFeature.SNAPMIRROR in available:
            recommendations.append(
                ProtectionRecommendation(
                    ProtectionFeature.SNAPMIRROR,
                    "high",
                    "Retained evidence benefits from a separately protected mirror",
                )
            )
        if ProtectionFeature.BACKUP in available:
            recommendations.append(
                ProtectionRecommendation(
                    ProtectionFeature.BACKUP,
                    "high",
                    "Long-lived evidence should have protection distinct from live storage",
                )
            )
    if logical_role in {"metadata", "results", "originals"}:
        if ProtectionFeature.SNAPSHOT in available:
            recommendations.append(
                ProtectionRecommendation(
                    ProtectionFeature.SNAPSHOT,
                    "medium",
                    "Fast point-in-time recovery is useful before migrations or operator changes",
                )
            )
    return tuple(recommendations)


def validate_object_size(resource: NetAppCloudResource, size_bytes: int) -> str | None:
    limit = resource.capabilities.s3_max_object_size_bytes
    if limit is not None and size_bytes > limit:
        return f"object-size-exceeds-provider-access-limit:{limit}"
    return None
