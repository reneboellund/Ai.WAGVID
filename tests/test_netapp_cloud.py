from wagvid_app.netapp_cloud import (
    FileProtocol,
    NetAppCloudResource,
    NetAppCloudService,
    ProtectionFeature,
    azure_netapp_files_capabilities,
    cloud_volumes_ontap_capabilities,
    fsx_ontap_s3_access_point_capabilities,
    google_cloud_netapp_volumes_capabilities,
    protection_recommendations,
    validate_object_size,
)


def resource(service, capabilities, **overrides):
    values = {
        "resource_id": "media-prod",
        "service": service,
        "cloud_provider": "fixture-cloud",
        "region": "eu-region-1",
        "account_scope": "account",
        "capacity_bytes": 10 * 1024**4,
        "capabilities": capabilities,
    }
    values.update(overrides)
    return NetAppCloudResource(**values)


def test_fsx_ontap_s3_access_point_does_not_claim_aws_s3_governance_features():
    capabilities = fsx_ontap_s3_access_point_capabilities()
    assert FileProtocol.S3_ACCESS_POINT in capabilities.protocols
    assert capabilities.s3_presigned_urls is False
    assert capabilities.s3_versioning is False
    assert capabilities.s3_object_lock is False
    assert capabilities.s3_lifecycle is False
    assert capabilities.s3_max_object_size_bytes == 50 * 1024**3


def test_fsx_object_size_limit_is_checked_before_transfer():
    fsx = resource(
        NetAppCloudService.FSX_ONTAP,
        fsx_ontap_s3_access_point_capabilities(),
    )
    assert validate_object_size(fsx, 50 * 1024**3) is None
    assert validate_object_size(fsx, 50 * 1024**3 + 1).startswith(
        "object-size-exceeds-provider-access-limit"
    )


def test_cloud_file_services_are_not_misrepresented_as_s3():
    anf = azure_netapp_files_capabilities()
    gcnv = google_cloud_netapp_volumes_capabilities()
    assert FileProtocol.NFS in anf.protocols
    assert FileProtocol.NFS in gcnv.protocols
    assert FileProtocol.ONTAP_S3 not in anf.protocols
    assert FileProtocol.S3_ACCESS_POINT not in gcnv.protocols


def test_cvo_keeps_ontap_management_and_protocol_capability_explicit():
    capabilities = cloud_volumes_ontap_capabilities(s3_enabled=True)
    assert capabilities.ontap_rest is True
    assert FileProtocol.ONTAP_S3 in capabilities.protocols
    assert ProtectionFeature.SNAPMIRROR in capabilities.protection


def test_originals_protection_recommendation_prefers_available_remote_protection():
    anf = resource(
        NetAppCloudService.AZURE_NETAPP_FILES,
        azure_netapp_files_capabilities(),
    )
    recommendations = protection_recommendations(anf, logical_role="originals")
    features = {item.feature for item in recommendations}
    assert ProtectionFeature.CROSS_REGION_REPLICATION in features
    assert ProtectionFeature.BACKUP in features
    assert ProtectionFeature.SNAPSHOT in features


def test_derivatives_do_not_receive_retained_evidence_protection_by_default():
    cvo = resource(
        NetAppCloudService.CLOUD_VOLUMES_ONTAP,
        cloud_volumes_ontap_capabilities(),
    )
    assert protection_recommendations(cvo, logical_role="derivatives") == ()


def test_locality_token_is_stable_and_provider_specific():
    gcnv = resource(
        NetAppCloudService.GOOGLE_CLOUD_NETAPP_VOLUMES,
        google_cloud_netapp_volumes_capabilities(),
        cloud_provider="gcp",
        region="europe-west4",
    )
    assert gcnv.locality_token == (
        "netapp:google-cloud-netapp-volumes:gcp:europe-west4:media-prod"
    )
