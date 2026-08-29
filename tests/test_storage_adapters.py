from datetime import UTC, datetime
from io import BytesIO

import pytest

from wagvid_app.aws_s3_provider import AwsS3ObjectStorageProvider, plan_aws_bucket_provisioning
from wagvid_app.object_provider import (
    ObjectLocation,
    ProviderType,
    StorageConnectionProfile,
    StorageFeature,
)
from wagvid_app.ontap_management import OntapCapabilities, OntapVersion
from wagvid_app.ontap_s3_provider import OntapS3ObjectStorageProvider
from wagvid_app.ootbi_s3_provider import OotbiS3ObjectStorageProvider, RetentionProtectedError
from wagvid_app.s3_validation import (
    CORE_OPERATIONS,
    ProviderSupportState,
    S3ContractValidation,
    run_safe_contract_probe,
)
from wagvid_app.storage_registry import StorageProviderRegistry, StorageRole, StorageRoute
from wagvid_app.vast_s3_provider import VastS3ObjectStorageProvider


class Retained(RuntimeError):
    pass


class FakeS3:
    def __init__(self, *, region="eu-central-1", public=False, retained=False):
        self.region = region
        self.public = public
        self.retained = retained
        self.objects = {}
        self.multipart = {}

    def head_bucket(self, *, Bucket):
        return {}

    def get_bucket_versioning(self, *, Bucket):
        return {"Status": "Enabled"}

    def get_object_lock_configuration(self, *, Bucket):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def get_bucket_lifecycle_configuration(self, *, Bucket):
        return {"Rules": []}

    def get_bucket_policy(self, *, Bucket):
        return {"Policy": "{}"}

    def get_public_access_block(self, *, Bucket):
        return {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }

    def get_bucket_encryption(self, *, Bucket):
        return {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}}

    def get_bucket_location(self, *, Bucket):
        return {"LocationConstraint": self.region}

    def get_bucket_acl(self, *, Bucket):
        if not self.public:
            return {"Grants": []}
        return {"Grants": [{"Grantee": {"URI": "http://acs.amazonaws.com/groups/global/AllUsers"}}]}

    def get_bucket_policy_status(self, *, Bucket):
        return {"PolicyStatus": {"IsPublic": self.public}}

    def put_object(self, *, Bucket, Key, Body, Metadata):
        self.objects[(Bucket, Key)] = (Body.read(), dict(Metadata))
        return {"VersionId": "v1"}

    def head_object(self, *, Bucket, Key, VersionId=None):
        body, metadata = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata, "VersionId": VersionId or "v1"}

    def get_object(self, *, Bucket, Key, Range=None, VersionId=None):
        body, _ = self.objects[(Bucket, Key)]
        if Range:
            start_text, end_text = Range.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(body) - 1
            body = body[start : end + 1]
        return {"Body": BytesIO(body)}

    def delete_object(self, *, Bucket, Key, VersionId=None):
        if self.retained:
            raise Retained("retention")
        self.objects.pop((Bucket, Key), None)
        return {}

    def create_multipart_upload(self, *, Bucket, Key, Metadata=None):
        upload_id = f"u{len(self.multipart) + 1}"
        self.multipart[upload_id] = {"bucket": Bucket, "key": Key, "metadata": dict(Metadata or {}), "parts": {}}
        return {"UploadId": upload_id}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        self.multipart[UploadId]["parts"][PartNumber] = Body.read()
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        state = self.multipart.pop(UploadId)
        body = b"".join(state["parts"][part["PartNumber"]] for part in MultipartUpload["Parts"])
        self.objects[(Bucket, Key)] = (body, state["metadata"])
        return {"VersionId": "v1"}

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.multipart.pop(UploadId, None)
        return {}

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return f"https://signed.example/{operation}/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"

    def list_multipart_uploads(self, *, Bucket, Prefix):
        uploads = [
            {"Key": state["key"], "UploadId": upload_id, "Initiated": "2026-08-17T07:00:00Z"}
            for upload_id, state in self.multipart.items()
            if state["bucket"] == Bucket and state["key"].startswith(Prefix)
        ]
        return {"Uploads": uploads, "IsTruncated": False}


def profile(provider_type, provider_id="p", *, region="eu-central-1"):
    return StorageConnectionProfile(
        provider_id=provider_id,
        provider_type=provider_type,
        endpoint="https://storage.example",
        region=region,
        credential_ref=f"secret://storage/{provider_id}",
    )


def validated(provider_id="p", bucket="originals", *, failed=()):
    return S3ContractValidation(
        provider_id=provider_id,
        bucket=bucket,
        state=ProviderSupportState.LIMITED if failed else ProviderSupportState.VALIDATED,
        tested_at=datetime(2026, 8, 17, 7, 0, tzinfo=UTC),
        passed_operations=CORE_OPERATIONS,
        failed_operations=tuple(failed),
        verified_features=frozenset({StorageFeature.RANGE_GET, StorageFeature.MULTIPART}),
    )


def test_safe_contract_probe_validates_core_without_real_endpoint():
    result = run_safe_contract_probe(
        FakeS3(),
        provider_id="lab",
        bucket="originals",
        now=datetime(2026, 8, 17, 7, 0, tzinfo=UTC),
    )
    assert result.core_validated
    assert result.state == ProviderSupportState.VALIDATED
    assert StorageFeature.RANGE_GET in result.verified_features
    assert StorageFeature.MULTIPART in result.verified_features


def test_aws_reference_adapter_reports_wrong_region_and_public_bucket():
    client = FakeS3(region="eu-west-1", public=True)
    provider = AwsS3ObjectStorageProvider(
        profile(ProviderType.AWS_S3, "aws"), client, buckets=["originals"], account_id="123456789012"
    )
    result = provider.preflight()
    assert any(item.startswith("wrong-region:originals") for item in result.blockers)
    assert "public-bucket-rejected:originals" in result.blockers
    assert result.identity_summary.endswith("…9012")


def test_aws_presign_and_dry_run_provisioning_are_non_mutating_contracts():
    client = FakeS3()
    provider = AwsS3ObjectStorageProvider(
        profile(ProviderType.AWS_S3, "aws"), client, buckets=["originals"]
    )
    location = ObjectLocation("aws", "originals", "org/video.mp4")
    get_request = provider.presign_get(location, expires_seconds=60)
    put_request = provider.presign_put(location, expected_sha256="a" * 64, expires_seconds=60)
    assert "get_object" in get_request.url
    assert put_request.headers["x-amz-meta-sha256"] == "a" * 64
    actions = plan_aws_bucket_provisioning(
        desired_buckets=["originals", "results"],
        existing_buckets=["originals"],
        region="eu-central-1",
        enable_versioning=True,
        object_lock_buckets=frozenset({"results"}),
    )
    assert any(item.action == "create-private-bucket" and item.bucket == "results" for item in actions)
    assert client.objects == {}


def test_ontap_release_caps_override_impossible_endpoint_claims():
    provider = OntapS3ObjectStorageProvider(
        profile(ProviderType.ONTAP_S3, "ontap"),
        FakeS3(),
        buckets=["originals"],
        ontap_capabilities=OntapCapabilities(OntapVersion(9, 10, 1)),
        platform_summary="AFF",
    )
    result = provider.preflight()
    assert StorageFeature.RANGE_GET in result.capabilities.features
    assert StorageFeature.VERSIONING not in result.capabilities.features
    assert StorageFeature.OBJECT_LOCK not in result.capabilities.features
    assert any("does-not-support-object-lock" in item for item in result.warnings)


def test_vast_is_unusable_until_each_bucket_has_contract_validation():
    provider = VastS3ObjectStorageProvider(
        profile(ProviderType.VAST_S3, "vast"), FakeS3(), buckets=["originals"]
    )
    assert "provider-contract-unvalidated:originals" in provider.preflight().blockers
    certified = VastS3ObjectStorageProvider(
        profile(ProviderType.VAST_S3, "vast"),
        FakeS3(),
        buckets=["originals"],
        validations=[validated("vast")],
        multiprotocol_view=True,
    )
    result = certified.preflight()
    assert result.usable
    assert StorageFeature.MULTIPART in result.capabilities.features
    assert any("multiprotocol-view" in item for item in result.warnings)


def test_ootbi_support_state_and_retention_denial_are_explicit_policy():
    unverified = OotbiS3ObjectStorageProvider(
        profile(ProviderType.OOTBI_S3, "ootbi"), FakeS3(), buckets=["originals"]
    )
    assert unverified.support_state == ProviderSupportState.UNVALIDATED
    assert not unverified.preflight().usable

    limited_record = validated("ootbi", failed=(("presigned-get", "unsupported"),))
    client = FakeS3(retained=True)
    provider = OotbiS3ObjectStorageProvider(
        profile(ProviderType.OOTBI_S3, "ootbi"),
        client,
        buckets=["originals"],
        validations=[limited_record],
        retention_error_classifier=lambda error: isinstance(error, Retained),
    )
    assert provider.support_state == ProviderSupportState.LIMITED
    client.objects[("originals", "retained.mp4")] = (b"x", {"sha256": "a" * 64})
    with pytest.raises(RetentionProtectedError, match="retention"):
        provider.delete(ObjectLocation("ootbi", "originals", "retained.mp4"))


def test_storage_registry_routes_roles_to_different_providers_without_domain_vendor_logic():
    aws = AwsS3ObjectStorageProvider(
        profile(ProviderType.AWS_S3, "aws"), FakeS3(), buckets=["temp"]
    )
    ootbi = OotbiS3ObjectStorageProvider(
        profile(ProviderType.OOTBI_S3, "ootbi"),
        FakeS3(),
        buckets=["originals"],
        validations=[validated("ootbi")],
    )
    registry = StorageProviderRegistry()
    registry.register(aws)
    registry.register(ootbi)
    registry.route(StorageRoute(StorageRole.ORIGINALS, "ootbi", "originals", "evidence"))
    registry.route(StorageRoute(StorageRole.TEMP, "aws", "temp", "scratch"))
    original = registry.resolve(StorageRole.ORIGINALS, "org/video.mp4")
    temp = registry.resolve(StorageRole.TEMP, "job/proxy.mp4")
    assert original.location.provider_id == "ootbi"
    assert original.location.key == "evidence/org/video.mp4"
    assert temp.location.provider_id == "aws"
    assert temp.location.key == "scratch/job/proxy.mp4"
