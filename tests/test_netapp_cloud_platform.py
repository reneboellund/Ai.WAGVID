from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest

from wagvid_app.cvo_control import (
    build_ontap_handoff,
    normalize_cvo_environment,
    plan_cvo_power_action,
    validate_cvo_cloud_mutation,
)
from wagvid_app.fsx_s3_access_point_provider import (
    FSX_ACCESS_POINT_MAX_OBJECT_SIZE,
    FsxOntapS3AccessPointProvider,
)
from wagvid_app.netapp_backup_recovery import (
    BackupJob,
    BackupJobState,
    BackupPolicy,
    backup_readiness,
    plan_backup_policy_mapping,
    plan_backup_restore,
    validate_backup_restore_cutover,
)
from wagvid_app.netapp_cloud import (
    NetAppCloudResource,
    NetAppCloudService,
    ProtectionFeature,
    azure_netapp_files_capabilities,
    cloud_volumes_ontap_capabilities,
    fsx_ontap_s3_access_point_capabilities,
    google_cloud_netapp_volumes_capabilities,
)
from wagvid_app.netapp_cloud_adapters import (
    normalize_azure_netapp_volume,
    normalize_cvo_volume,
    normalize_fsx_ontap_volume,
    normalize_fsx_s3_access_point,
    normalize_google_netapp_volume,
)
from wagvid_app.netapp_cloud_control import (
    NetAppCloudAction,
    NetAppCloudApproval,
    NetAppCloudOperation,
    NetAppCloudPlan,
    ProtectionState,
    RecoveryPoint,
    validate_approval,
)
from wagvid_app.netapp_cloud_orchestration import (
    DesiredCloudVolume,
    apply_plan,
    plan_fsx_s3_access_point,
    plan_replication_action,
    plan_volume_reconciliation,
)
from wagvid_app.object_provider import (
    ObjectLocation,
    ProviderType,
    StorageConnectionProfile,
    StorageFeature,
)
from wagvid_app.shared_file_provider import (
    SharedFileProtocol,
    WorkerMountContext,
    plan_worker_mount,
)

NOW = datetime(2026, 8, 17, 8, 30, tzinfo=UTC)


class FakeS3:
    def head_bucket(self, *, Bucket): return {}
    def get_bucket_versioning(self, *, Bucket): return {"Status": "Enabled"}
    def get_object_lock_configuration(self, *, Bucket): return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}
    def get_bucket_lifecycle_configuration(self, *, Bucket): return {"Rules": []}
    def get_bucket_policy(self, *, Bucket): return {"Policy": "{}"}
    def get_public_access_block(self, *, Bucket):
        return {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}}
    def put_object(self, **kwargs): return {}
    def head_object(self, **kwargs): return {"ContentLength": 0, "Metadata": {"sha256": "a" * 64}}
    def get_object(self, **kwargs): return {"Body": BytesIO(b"")}
    def delete_object(self, **kwargs): return {}
    def create_multipart_upload(self, **kwargs): return {"UploadId": "u1"}
    def upload_part(self, **kwargs): return {"ETag": "etag"}
    def complete_multipart_upload(self, **kwargs): return {}
    def abort_multipart_upload(self, **kwargs): return {}


def resource(service, *, resource_id="vol-1", health="available", capacity=1000):
    caps = {
        NetAppCloudService.FSX_ONTAP: fsx_ontap_s3_access_point_capabilities(),
        NetAppCloudService.AZURE_NETAPP_FILES: azure_netapp_files_capabilities(),
        NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES: google_cloud_netapp_volumes_capabilities(),
        NetAppCloudService.CLOUD_VOLUMES_ONTAP: cloud_volumes_ontap_capabilities(),
    }[service]
    cloud = {
        NetAppCloudService.FSX_ONTAP: "aws",
        NetAppCloudService.AZURE_NETAPP_FILES: "azure",
        NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES: "gcp",
        NetAppCloudService.CLOUD_VOLUMES_ONTAP: "aws",
    }[service]
    return NetAppCloudResource(
        resource_id=resource_id,
        service=service,
        cloud_provider=cloud,
        region="eu-test-1",
        account_scope="account",
        capacity_bytes=capacity,
        capabilities=caps,
        network_scope="net-1",
        service_level="standard",
        health=health,
        mount_reference="10.0.0.10:/wagvid",
    )


def test_shared_file_mount_is_private_region_and_identity_aware():
    normalized = normalize_azure_netapp_volume(
        {
            "id": "/subscriptions/x/volumes/v1",
            "location": "northeurope",
            "properties": {"usageThreshold": 1024**4, "provisioningState": "Succeeded", "serviceLevel": "Premium"},
        },
        provider_id="anf",
        subscription_scope="sub-x",
        protocol=SharedFileProtocol.NFS,
        mount_reference="10.1.0.4:/wagvid",
        network_scope="vnet-storage",
    )
    assert normalized.resource.health == "ready"
    preflight, plan = plan_worker_mount(
        normalized.shared_file,
        WorkerMountContext("worker-1", "azure", "northeurope", frozenset({"vnet-storage"})),
        require_write=True,
    )
    assert preflight.usable
    assert plan.locality_token.startswith("file:azure-netapp-files")

    blocked, _ = plan_worker_mount(
        normalized.shared_file,
        WorkerMountContext("worker-2", "azure", "westeurope", frozenset({"vnet-storage"})),
    )
    assert not blocked.usable
    assert any(item.startswith("cross-region-mount-rejected") for item in blocked.blockers)


def test_smb_shared_file_requires_worker_identity_reference():
    normalized = normalize_google_netapp_volume(
        {"name": "projects/p/locations/eu/volumes/v1", "location": "europe-west4", "capacityGib": 2048, "state": "READY"},
        provider_id="gcnv",
        project_scope="project-p",
        protocol=SharedFileProtocol.SMB,
        mount_reference="//10.2.0.5/wagvid",
        network_scope="vpc-storage",
    )
    blocked, _ = plan_worker_mount(
        normalized.shared_file,
        WorkerMountContext("worker", "gcp", "europe-west4", frozenset({"vpc-storage"})),
    )
    assert "smb-worker-identity-required" in blocked.blockers


def test_fsx_normalization_uses_ontap_volume_mib_and_access_point_limits():
    normalized = normalize_fsx_ontap_volume(
        {"VolumeId": "fsvol-1", "Lifecycle": "AVAILABLE", "OntapVolumeConfiguration": {"SizeInMegabytes": 1024}},
        provider_id="fsx",
        account_scope="123456789012",
        region="eu-central-1",
        protocol=SharedFileProtocol.NFS,
        mount_reference="svm.example:/wagvid",
        network_scope="vpc-1",
    )
    assert normalized.resource.capacity_bytes == 1024 * 1024**2
    ap = normalize_fsx_s3_access_point(
        {"AccessPointId": "ap-1", "Alias": "ap-alias", "VolumeId": "fsvol-1", "DirectoryPath": "/evidence"},
        provider_id="fsx-ap",
        region="eu-central-1",
        network_scope="vpc-1",
    )
    assert ap.max_object_size_bytes == 50 * 1024**3
    assert not ap.presigned_urls and not ap.versioning and not ap.object_lock


def test_fsx_s3_access_point_strips_bucket_governance_and_blocks_large_object():
    provider = FsxOntapS3AccessPointProvider(
        StorageConnectionProfile(
            provider_id="fsx-ap",
            provider_type=ProviderType.GENERIC_S3,
            endpoint="https://ap.example",
            region="eu-central-1",
        ),
        FakeS3(),
        access_point_aliases=["alias"],
    )
    preflight = provider.preflight()
    assert preflight.capabilities.max_object_size_bytes == FSX_ACCESS_POINT_MAX_OBJECT_SIZE
    assert StorageFeature.RANGE_GET in preflight.capabilities.features
    assert StorageFeature.VERSIONING not in preflight.capabilities.features
    assert StorageFeature.OBJECT_LOCK not in preflight.capabilities.features
    assert StorageFeature.PRESIGNED_GET not in preflight.capabilities.features
    with pytest.raises(ValueError, match="exceeds"):
        provider.put_verified(
            ObjectLocation("fsx-ap", "alias", "too-large.bin"),
            BytesIO(b""),
            expected_size=FSX_ACCESS_POINT_MAX_OBJECT_SIZE + 1,
            expected_sha256="a" * 64,
        )


def test_cloud_action_plans_reject_secrets_and_require_destructive_confirmation():
    with pytest.raises(ValueError, match="Secret material"):
        NetAppCloudAction(
            NetAppCloudOperation.CREATE_VOLUME,
            "anf", "vol", NetAppCloudService.AZURE_NETAPP_FILES,
            {"client_secret": "plaintext"},
        )
    action = NetAppCloudAction(
        NetAppCloudOperation.REVERSE_REPLICATION,
        "gcnv", "vol", NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES,
        {"relationship_id": "rel-1"}, destructive=True,
    )
    plan = NetAppCloudPlan((action,))
    bad = NetAppCloudApproval(plan.digest, "admin", NOW, NOW + timedelta(minutes=5), "APPLY NETAPP CLOUD CHANGES")
    with pytest.raises(ValueError, match="DESTRUCTIVE"):
        validate_approval(plan, bad, now=NOW)
    good = NetAppCloudApproval(plan.digest, "admin", NOW, NOW + timedelta(minutes=5), "APPLY DESTRUCTIVE NETAPP PROTECTION CHANGE")
    validate_approval(plan, good, now=NOW)


def test_volume_reconciliation_is_idempotent_and_never_shrinks_automatically():
    current = resource(NetAppCloudService.AZURE_NETAPP_FILES, capacity=2000)
    desired = DesiredCloudVolume(
        "anf", current.resource_id, current.service, "azure", current.region,
        current.account_scope, 2000, SharedFileProtocol.NFS, current.network_scope,
        current.service_level,
    )
    assert plan_volume_reconciliation(desired, current).actions == ()
    shrink = DesiredCloudVolume(
        "anf", current.resource_id, current.service, "azure", current.region,
        current.account_scope, 1000, SharedFileProtocol.NFS, current.network_scope,
        current.service_level,
    )
    assert "automatic-volume-shrink-rejected" in plan_volume_reconciliation(shrink, current).blockers


def test_fsx_access_point_plan_blocks_s3_governance_requests():
    fsx = resource(NetAppCloudService.FSX_ONTAP)
    blocked = plan_fsx_s3_access_point(
        fsx,
        provider_id="fsx",
        access_point_id="ap-1",
        directory_path="/evidence",
        requested_features=frozenset({"versioning", "object-lock"}),
    )
    assert not blocked.applicable
    assert "fsx-s3-access-point-unsupported:object-lock" in blocked.blockers
    assert "fsx-s3-access-point-unsupported:versioning" in blocked.blockers


def test_replication_feature_is_cloud_native_for_gcnv_and_snapmirror_for_cvo():
    gcnv = resource(NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES)
    reverse = plan_replication_action(
        gcnv, provider_id="gcnv", operation=NetAppCloudOperation.REVERSE_REPLICATION,
        relationship_id="rel-1",
    )
    assert reverse.applicable and reverse.has_destructive_actions

    cvo = resource(NetAppCloudService.CLOUD_VOLUMES_ONTAP)
    cvo_sync = plan_replication_action(
        cvo, provider_id="cvo", operation=NetAppCloudOperation.SYNC_REPLICATION,
        relationship_id="mirror-1",
    )
    assert cvo_sync.applicable

    fsx = resource(NetAppCloudService.FSX_ONTAP)
    fsx_sync = plan_replication_action(
        fsx, provider_id="fsx", operation=NetAppCloudOperation.SYNC_REPLICATION,
        relationship_id="mirror-1",
    )
    assert "protection-feature-unavailable:snapmirror" in fsx_sync.blockers


def test_plan_apply_uses_deterministic_idempotency_keys():
    class FakeApi:
        def __init__(self): self.calls = []
        def execute(self, operation, *, resource_id, details, idempotency_key):
            self.calls.append((operation, resource_id, idempotency_key))
            return f"operation-{len(self.calls)}"

    plan = NetAppCloudPlan((NetAppCloudAction(
        NetAppCloudOperation.CREATE_SNAPSHOT,
        "anf", "vol", NetAppCloudService.AZURE_NETAPP_FILES,
        {"snapshot_name": "before-upgrade", "reason": "upgrade"},
    ),))
    approval = NetAppCloudApproval(plan.digest, "admin", NOW, NOW + timedelta(minutes=5), "APPLY NETAPP CLOUD CHANGES")
    api = FakeApi()
    applied = apply_plan(plan, approval, api=api, now=NOW)
    assert applied[0].provider_operation_id == "operation-1"
    assert api.calls[0][2] == f"{plan.digest}:0"


def test_cvo_handoff_separates_console_from_ontap_and_blocks_low_level_disk_mutation():
    environment = normalize_cvo_environment(
        {
            "id": "we-1", "name": "wagvid-cvo", "region": "eu-central-1",
            "topology": "ha", "ontap_version": "9.17.1", "status": "online",
            "ontap_management_endpoint_ref": "https://10.0.0.20",
            "ontap_s3_endpoint_ref": "config://cvo/s3-endpoint",
        },
        provider_id="cvo", cloud_provider="aws", account_scope="account-1",
    )
    handoff = build_ontap_handoff(environment, management_credential_ref="secret://cvo/ontap-admin")
    assert handoff.management_credential_ref.startswith("secret://")
    assert plan_cvo_power_action(environment, start=True).actions == ()
    with pytest.raises(ValueError, match="Console-supported"):
        validate_cvo_cloud_mutation("create-cloud-disk")


def test_backup_recovery_is_protection_only_and_restore_is_staging_first():
    anf = resource(NetAppCloudService.AZURE_NETAPP_FILES)
    policy = BackupPolicy("policy-1", "retained", "90d", "NetApp managed backup")
    mapping, enable = plan_backup_policy_mapping(
        anf, provider_id="anf", logical_role="originals", policy=policy
    )
    assert mapping.logical_role == "originals" and enable.applicable

    protection = ProtectionState("anf", anf.resource_id, ProtectionFeature.BACKUP, True, "healthy")
    assert backup_readiness(
        protection,
        (BackupJob("job-1", "anf", anf.resource_id, BackupJobState.SUCCEEDED),),
    ).ready

    point = RecoveryPoint(
        "anf", anf.resource_id, "rp-1", ProtectionFeature.BACKUP, NOW, source_hash="a" * 64
    )
    restore = plan_backup_restore(point, alternate_target="anf-restore-vol")
    assert restore.staging and restore.cutover_allowed
    blockers = validate_backup_restore_cutover(
        restore,
        restored_sha256="b" * 64,
        object_or_file_inventory_verified=True,
        target_provider_healthy=True,
        canonical_routing_still_unchanged=True,
        confirmation="CUT OVER VERIFIED NETAPP RESTORE",
    )
    assert "restored-sha256-mismatch" in blockers


def test_cvo_volume_normalization_keeps_file_and_optional_s3_paths_separate():
    normalized = normalize_cvo_volume(
        {"id": "vol-1", "size_gib": 1024, "status": "online", "s3_endpoint_reference": "config://cvo/s3"},
        provider_id="cvo", cloud_provider="aws", account_scope="account",
        region="eu-central-1", protocol=SharedFileProtocol.NFS,
        mount_reference="10.0.0.20:/wagvid", network_scope="vpc-1", s3_enabled=True,
    )
    assert normalized.resource.health == "ready"
    assert normalized.shared_file.mount_reference.endswith(":/wagvid")
    assert normalized.resource.s3_endpoint_reference == "config://cvo/s3"
