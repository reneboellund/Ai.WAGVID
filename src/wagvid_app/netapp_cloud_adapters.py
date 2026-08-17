"""Provider response normalization for NetApp cloud/shared-file services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .netapp_cloud import (
    NetAppCloudResource,
    NetAppCloudService,
    azure_netapp_files_capabilities,
    cloud_volumes_ontap_capabilities,
    fsx_ontap_s3_access_point_capabilities,
    google_cloud_netapp_volumes_capabilities,
)
from .shared_file_provider import (
    SharedFileCapabilities,
    SharedFileFeature,
    SharedFileProtocol,
    SharedFileResource,
)


@dataclass(frozen=True)
class FsxS3AccessPoint:
    provider_id: str
    access_point_id: str
    alias: str
    region: str
    volume_id: str
    directory_path: str
    network_scope: str | None
    max_object_size_bytes: int = 50 * 1024**3
    presigned_urls: bool = False
    versioning: bool = False
    object_lock: bool = False
    lifecycle: bool = False

    @property
    def locality_token(self) -> str:
        return f"fsx-s3-access-point:aws:{self.region}:{self.access_point_id}"


@dataclass(frozen=True)
class NormalizedCloudStorage:
    resource: NetAppCloudResource
    shared_file: SharedFileResource | None = None
    fsx_s3_access_point: FsxS3AccessPoint | None = None


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required provider field: {name}")
    return text


def _capacity_bytes(value: Any, *, multiplier: int = 1) -> int | None:
    if value in (None, ""):
        return None
    number = int(value)
    if number < 0:
        raise ValueError("Provider capacity cannot be negative")
    return number * multiplier


def _health(value: Any) -> str:
    state = str(value or "unknown").casefold().replace("_", "-")
    mapping = {
        "succeeded": "ready", "online": "ready", "running": "ready",
        "active": "ready", "created": "ready", "available": "available",
        "ready": "ready", "healthy": "healthy", "stopped": "stopped",
    }
    return mapping.get(state, state)


def _shared_capabilities(service: NetAppCloudService) -> SharedFileCapabilities:
    common = {SharedFileFeature.READ, SharedFileFeature.WRITE, SharedFileFeature.SNAPSHOT}
    if service == NetAppCloudService.FSX_ONTAP:
        features = common | {SharedFileFeature.BACKUP, SharedFileFeature.CLONE}
    elif service == NetAppCloudService.AZURE_NETAPP_FILES:
        features = common | {
            SharedFileFeature.BACKUP,
            SharedFileFeature.CROSS_REGION_REPLICATION,
            SharedFileFeature.FILE_RESTORE,
            SharedFileFeature.VOLUME_REVERT,
        }
    elif service == NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES:
        features = common | {SharedFileFeature.CROSS_REGION_REPLICATION, SharedFileFeature.CLONE}
    else:
        features = common | {
            SharedFileFeature.BACKUP,
            SharedFileFeature.CLONE,
            SharedFileFeature.CROSS_REGION_REPLICATION,
        }
    return SharedFileCapabilities(
        protocols=frozenset({SharedFileProtocol.NFS, SharedFileProtocol.SMB}),
        features=frozenset(features),
        private_network_required=True,
    )


def normalize_fsx_ontap_volume(
    record: Mapping[str, Any], *, provider_id: str, account_scope: str, region: str,
    protocol: SharedFileProtocol, mount_reference: str, network_scope: str,
) -> NormalizedCloudStorage:
    volume_id = _required(record.get("VolumeId") or record.get("id"), "VolumeId")
    ontap = record.get("OntapVolumeConfiguration") if isinstance(record.get("OntapVolumeConfiguration"), Mapping) else {}
    capacity_bytes = _capacity_bytes(record.get("capacity_bytes"))
    if capacity_bytes is None and ontap.get("SizeInMegabytes") is not None:
        capacity_bytes = _capacity_bytes(ontap.get("SizeInMegabytes"), multiplier=1024**2)
    health = _health(record.get("Lifecycle") or record.get("health"))
    resource = NetAppCloudResource(
        resource_id=volume_id,
        service=NetAppCloudService.FSX_ONTAP,
        cloud_provider="aws",
        region=_required(region, "region"),
        account_scope=_required(account_scope, "account_scope"),
        capacity_bytes=capacity_bytes,
        capabilities=fsx_ontap_s3_access_point_capabilities(),
        network_scope=_required(network_scope, "network_scope"),
        service_level=str(ontap.get("StorageEfficiencyEnabled", "fsx-ontap")),
        health=health,
        mount_reference=mount_reference,
    )
    shared = SharedFileResource(
        provider_id=provider_id,
        resource_id=volume_id,
        provider_type=NetAppCloudService.FSX_ONTAP.value,
        cloud_provider="aws",
        region=region,
        account_scope=account_scope,
        protocol=protocol,
        mount_reference=_required(mount_reference, "mount_reference"),
        capacity_bytes=capacity_bytes,
        capabilities=_shared_capabilities(NetAppCloudService.FSX_ONTAP),
        network_scope=network_scope,
        health=health,
    )
    return NormalizedCloudStorage(resource, shared_file=shared)


def normalize_fsx_s3_access_point(
    record: Mapping[str, Any], *, provider_id: str, region: str, network_scope: str | None,
) -> FsxS3AccessPoint:
    path = str(record.get("DirectoryPath") or record.get("directory_path") or "/").replace("\\", "/")
    if not path.startswith("/") or ".." in path.split("/"):
        raise ValueError("Unsafe FSx S3 access point directory path")
    return FsxS3AccessPoint(
        provider_id=provider_id,
        access_point_id=_required(record.get("AccessPointId") or record.get("access_point_id"), "AccessPointId"),
        alias=_required(record.get("Alias") or record.get("alias"), "Alias"),
        region=_required(region, "region"),
        volume_id=_required(record.get("VolumeId") or record.get("volume_id"), "VolumeId"),
        directory_path=path,
        network_scope=network_scope,
    )


def normalize_azure_netapp_volume(
    record: Mapping[str, Any], *, provider_id: str, subscription_scope: str,
    protocol: SharedFileProtocol, mount_reference: str, network_scope: str,
) -> NormalizedCloudStorage:
    resource_id = _required(record.get("id") or record.get("name"), "id")
    region = _required(record.get("location") or record.get("region"), "location")
    properties = record.get("properties") if isinstance(record.get("properties"), Mapping) else record
    capacity_bytes = _capacity_bytes(properties.get("usageThreshold") or properties.get("capacity_bytes"))
    health = _health(properties.get("provisioningState") or properties.get("health"))
    resource = NetAppCloudResource(
        resource_id=resource_id,
        service=NetAppCloudService.AZURE_NETAPP_FILES,
        cloud_provider="azure",
        region=region,
        account_scope=_required(subscription_scope, "subscription_scope"),
        capacity_bytes=capacity_bytes,
        capabilities=azure_netapp_files_capabilities(),
        network_scope=_required(network_scope, "network_scope"),
        service_level=str(properties.get("serviceLevel") or "unknown"),
        health=health,
        mount_reference=mount_reference,
    )
    shared = SharedFileResource(
        provider_id=provider_id,
        resource_id=resource_id,
        provider_type=NetAppCloudService.AZURE_NETAPP_FILES.value,
        cloud_provider="azure",
        region=region,
        account_scope=subscription_scope,
        protocol=protocol,
        mount_reference=_required(mount_reference, "mount_reference"),
        capacity_bytes=capacity_bytes,
        capabilities=_shared_capabilities(NetAppCloudService.AZURE_NETAPP_FILES),
        network_scope=network_scope,
        service_level=resource.service_level,
        health=health,
    )
    return NormalizedCloudStorage(resource, shared_file=shared)


def normalize_google_netapp_volume(
    record: Mapping[str, Any], *, provider_id: str, project_scope: str,
    protocol: SharedFileProtocol, mount_reference: str, network_scope: str,
) -> NormalizedCloudStorage:
    resource_id = _required(record.get("name") or record.get("id"), "name")
    region = _required(record.get("location") or record.get("region"), "location")
    capacity_bytes = (
        _capacity_bytes(record.get("capacityGib"), multiplier=1024**3)
        if record.get("capacityGib") is not None
        else _capacity_bytes(record.get("capacity_bytes"))
    )
    health = _health(record.get("state") or record.get("health"))
    resource = NetAppCloudResource(
        resource_id=resource_id,
        service=NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES,
        cloud_provider="gcp",
        region=region,
        account_scope=_required(project_scope, "project_scope"),
        capacity_bytes=capacity_bytes,
        capabilities=google_cloud_netapp_volumes_capabilities(),
        network_scope=_required(network_scope, "network_scope"),
        service_level=str(record.get("serviceLevel") or "unknown"),
        health=health,
        mount_reference=mount_reference,
    )
    shared = SharedFileResource(
        provider_id=provider_id,
        resource_id=resource_id,
        provider_type=NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES.value,
        cloud_provider="gcp",
        region=region,
        account_scope=project_scope,
        protocol=protocol,
        mount_reference=_required(mount_reference, "mount_reference"),
        capacity_bytes=capacity_bytes,
        capabilities=_shared_capabilities(NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES),
        network_scope=network_scope,
        service_level=resource.service_level,
        health=health,
    )
    return NormalizedCloudStorage(resource, shared_file=shared)


def normalize_cvo_volume(
    record: Mapping[str, Any], *, provider_id: str, cloud_provider: str, account_scope: str,
    region: str, protocol: SharedFileProtocol, mount_reference: str, network_scope: str,
    s3_enabled: bool,
) -> NormalizedCloudStorage:
    resource_id = _required(record.get("id") or record.get("name"), "id")
    if record.get("capacity_bytes") is not None:
        capacity_bytes = _capacity_bytes(record.get("capacity_bytes"))
    elif record.get("size_gib") is not None:
        capacity_bytes = _capacity_bytes(record.get("size_gib"), multiplier=1024**3)
    else:
        capacity_bytes = None
    health = _health(record.get("health") or record.get("status"))
    resource = NetAppCloudResource(
        resource_id=resource_id,
        service=NetAppCloudService.CLOUD_VOLUMES_ONTAP,
        cloud_provider=_required(cloud_provider, "cloud_provider"),
        region=_required(region, "region"),
        account_scope=_required(account_scope, "account_scope"),
        capacity_bytes=capacity_bytes,
        capabilities=cloud_volumes_ontap_capabilities(s3_enabled=s3_enabled),
        network_scope=_required(network_scope, "network_scope"),
        service_level=str(record.get("service_level") or record.get("tiering_policy") or "unknown"),
        health=health,
        mount_reference=mount_reference,
        s3_endpoint_reference=str(record.get("s3_endpoint_reference") or "") or None,
    )
    shared = SharedFileResource(
        provider_id=provider_id,
        resource_id=resource_id,
        provider_type=NetAppCloudService.CLOUD_VOLUMES_ONTAP.value,
        cloud_provider=cloud_provider,
        region=region,
        account_scope=account_scope,
        protocol=protocol,
        mount_reference=_required(mount_reference, "mount_reference"),
        capacity_bytes=capacity_bytes,
        capabilities=_shared_capabilities(NetAppCloudService.CLOUD_VOLUMES_ONTAP),
        network_scope=network_scope,
        service_level=resource.service_level,
        health=health,
    )
    return NormalizedCloudStorage(resource, shared_file=shared)
