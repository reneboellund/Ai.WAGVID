import hashlib
from io import BytesIO

import pytest

from wagvid_app.object_provider import (
    ObjectLocation,
    ObjectStorageProvider,
    ProviderType,
    StorageConnectionProfile,
    StorageFeature,
)
from wagvid_app.s3_provider import S3ObjectStorageProvider, inspect_bucket, preflight_existing_buckets
from wagvid_app.storage import ObjectIntegrityError
from wagvid_app.wasabi_object_provider import build_wasabi_object_provider


class FakeS3:
    def __init__(self, *, fail=None):
        self.fail = set(fail or [])
        self.objects = {}
        self.multipart = {}
        self.put_calls = 0

    def _value(self, name, value):
        if name in self.fail:
            raise RuntimeError(name)
        return value

    def head_bucket(self, *, Bucket):
        return self._value("head", {})

    def get_bucket_versioning(self, *, Bucket):
        return self._value("versioning", {"Status": "Enabled"})

    def get_object_lock_configuration(self, *, Bucket):
        return self._value(
            "object-lock", {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}
        )

    def get_bucket_lifecycle_configuration(self, *, Bucket):
        return self._value("lifecycle", {"Rules": []})

    def get_bucket_policy(self, *, Bucket):
        return self._value("policy", {"Policy": "{}"})

    def get_public_access_block(self, *, Bucket):
        return self._value(
            "public-block",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            },
        )

    def put_object(self, *, Bucket, Key, Body, Metadata):
        self.put_calls += 1
        self.objects[(Bucket, Key)] = (Body.read(), dict(Metadata))
        return {"VersionId": "v1"}

    def head_object(self, *, Bucket, Key, VersionId=None):
        body, metadata = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}

    def get_object(self, *, Bucket, Key, Range=None, VersionId=None):
        body, _ = self.objects[(Bucket, Key)]
        if Range:
            value = Range.removeprefix("bytes=")
            start_text, end_text = value.split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(body) - 1
            body = body[start : end + 1]
        return {"Body": BytesIO(body)}

    def delete_object(self, *, Bucket, Key, VersionId=None):
        self.objects.pop((Bucket, Key), None)
        return {}

    def create_multipart_upload(self, *, Bucket, Key, Metadata):
        upload_id = f"upload-{len(self.multipart) + 1}"
        self.multipart[upload_id] = {
            "bucket": Bucket,
            "key": Key,
            "metadata": dict(Metadata),
            "parts": {},
        }
        return {"UploadId": upload_id}

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body):
        state = self.multipart[UploadId]
        assert (Bucket, Key) == (state["bucket"], state["key"])
        state["parts"][PartNumber] = Body.read()
        return {"ETag": f'"etag-{PartNumber}"'}

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload):
        state = self.multipart.pop(UploadId)
        part_numbers = [item["PartNumber"] for item in MultipartUpload["Parts"]]
        body = b"".join(state["parts"][number] for number in part_numbers)
        self.objects[(Bucket, Key)] = (body, state["metadata"])
        return {"VersionId": "v1"}

    def abort_multipart_upload(self, *, Bucket, Key, UploadId):
        self.multipart.pop(UploadId, None)
        return {}


def profile(provider_type=ProviderType.GENERIC_S3):
    return StorageConnectionProfile(
        provider_id="primary",
        provider_type=provider_type,
        endpoint="https://storage.example",
    )


def test_bucket_probe_only_advertises_active_or_verified_features():
    probe = inspect_bucket(FakeS3(fail={"object-lock", "lifecycle"}), "originals")
    assert probe.reachable is True
    assert StorageFeature.VERSIONING in probe.features
    assert StorageFeature.OBJECT_LOCK not in probe.features
    assert StorageFeature.LIFECYCLE not in probe.features
    assert StorageFeature.RANGE_GET not in probe.features
    assert any("object-lock-unverified" in warning for warning in probe.warnings)


def test_bucket_probe_does_not_treat_disabled_governance_as_active():
    class Disabled(FakeS3):
        def get_bucket_versioning(self, *, Bucket):
            return {}

        def get_object_lock_configuration(self, *, Bucket):
            return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}}

        def get_public_access_block(self, *, Bucket):
            return {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True}}

    probe = inspect_bucket(Disabled(), "originals")
    assert StorageFeature.VERSIONING not in probe.features
    assert StorageFeature.OBJECT_LOCK not in probe.features
    assert StorageFeature.PUBLIC_ACCESS_BLOCK not in probe.features
    assert "object-lock-not-enabled" in probe.warnings
    assert "public-access-block-not-fully-enabled" in probe.warnings


def test_bucket_probe_does_not_treat_unreachable_bucket_as_capable():
    probe = inspect_bucket(FakeS3(fail={"head"}), "missing")
    assert probe.reachable is False
    assert probe.features == frozenset()


def test_provider_preflight_intersects_bucket_state_and_adds_only_certified_protocol_features():
    preflight, probes = preflight_existing_buckets(
        profile(ProviderType.ONTAP_S3),
        FakeS3(fail={"lifecycle"}),
        buckets=["results", "originals"],
        extra_verified_features=frozenset({StorageFeature.RANGE_GET, StorageFeature.MULTIPART}),
    )
    assert preflight.connected is True
    assert [probe.bucket for probe in probes] == ["originals", "results"]
    assert StorageFeature.VERSIONING in preflight.capabilities.features
    assert StorageFeature.LIFECYCLE not in preflight.capabilities.features
    assert StorageFeature.RANGE_GET in preflight.capabilities.features


def test_provider_preflight_blocks_when_any_required_bucket_is_unreachable():
    class OneMissing(FakeS3):
        def head_bucket(self, *, Bucket):
            if Bucket == "results":
                raise RuntimeError("missing")
            return {}

    preflight, _ = preflight_existing_buckets(
        profile(ProviderType.VAST_S3), OneMissing(), buckets=["originals", "results"]
    )
    assert preflight.usable is False
    assert "bucket-unreachable:results" in preflight.blockers


def test_data_plane_verifies_source_before_put_and_round_trips_with_range():
    client = FakeS3()
    provider = S3ObjectStorageProvider(
        profile(),
        client,
        buckets=["originals"],
        verified_features=frozenset({StorageFeature.RANGE_GET}),
    )
    location = ObjectLocation("primary", "originals", "org/video.mp4")
    payload = b"0123456789"
    digest = hashlib.sha256(payload).hexdigest()

    stored = provider.put_verified(
        location, BytesIO(payload), expected_size=len(payload), expected_sha256=digest
    )
    assert stored.sha256 == digest
    assert provider.open_read(location).read() == payload
    assert provider.open_range(location, start=2, end=5).read() == b"2345"

    with pytest.raises(ObjectIntegrityError, match="Source object"):
        provider.put_verified(
            ObjectLocation("primary", "originals", "org/bad.mp4"),
            BytesIO(payload),
            expected_size=len(payload),
            expected_sha256="0" * 64,
        )
    assert client.put_calls == 1


def test_data_plane_rejects_cross_provider_and_unmapped_bucket_locations():
    provider = S3ObjectStorageProvider(profile(), FakeS3(), buckets=["originals"])
    with pytest.raises(ValueError, match="another storage provider"):
        provider.inspect(ObjectLocation("other", "originals", "x"))
    with pytest.raises(ValueError, match="not mapped"):
        provider.inspect(ObjectLocation("primary", "results", "x"))


def test_multipart_preserves_canonical_hash_metadata_and_validates_completion():
    client = FakeS3()
    provider = S3ObjectStorageProvider(
        profile(),
        client,
        buckets=["originals"],
        verified_features=frozenset({StorageFeature.MULTIPART}),
    )
    payload = b"abcdefgh"
    digest = hashlib.sha256(payload).hexdigest()
    location = ObjectLocation("primary", "originals", "org/large.mp4")
    handle = provider.create_multipart(location, expected_sha256=digest)
    etag1 = provider.upload_part(handle, part_number=1, body=BytesIO(payload[:4]))
    etag2 = provider.upload_part(handle, part_number=2, body=BytesIO(payload[4:]))
    stored = provider.complete_multipart(
        handle, parts=[(1, etag1), (2, etag2)], expected_size=len(payload)
    )
    assert stored.sha256 == digest
    assert provider.open_read(location).read() == payload


def test_wasabi_bridge_implements_common_object_provider_without_replacing_setup_logic():
    client = FakeS3()
    provider = build_wasabi_object_provider(
        provider_id="wasabi-primary",
        endpoint="https://s3.eu-central-1.wasabisys.com",
        region="eu-central-1",
        credential_ref="secret://storage/wasabi-primary",
        client=client,
        buckets=["originals"],
    )
    assert isinstance(provider, ObjectStorageProvider)
    assert provider.profile.provider_type == ProviderType.WASABI
    assert StorageFeature.RANGE_GET in provider.preflight().capabilities.features
    assert StorageFeature.MULTIPART in provider.preflight().capabilities.features
