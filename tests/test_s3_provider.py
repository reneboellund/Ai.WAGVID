from wagvid_app.object_provider import (
    ProviderType,
    StorageConnectionProfile,
    StorageFeature,
)
from wagvid_app.s3_provider import inspect_bucket, preflight_existing_buckets


class FakeS3:
    def __init__(self, *, fail=None):
        self.fail = set(fail or [])

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
        return self._value("public-block", {"PublicAccessBlockConfiguration": {}})


def test_bucket_probe_only_advertises_verified_features():
    probe = inspect_bucket(FakeS3(fail={"object-lock", "lifecycle"}), "originals")
    assert probe.reachable is True
    assert StorageFeature.VERSIONING in probe.features
    assert StorageFeature.OBJECT_LOCK not in probe.features
    assert StorageFeature.LIFECYCLE not in probe.features
    assert StorageFeature.RANGE_GET in probe.features
    assert any("object-lock-unverified" in warning for warning in probe.warnings)


def test_bucket_probe_does_not_treat_unreachable_bucket_as_capable():
    probe = inspect_bucket(FakeS3(fail={"head"}), "missing")
    assert probe.reachable is False
    assert probe.features == frozenset()


def test_provider_preflight_uses_common_capabilities_across_role_buckets():
    profile = StorageConnectionProfile(
        provider_id="ontap-primary",
        provider_type=ProviderType.ONTAP_S3,
        endpoint="https://ontap.example",
    )
    preflight, probes = preflight_existing_buckets(
        profile,
        FakeS3(fail={"lifecycle"}),
        buckets=["results", "originals"],
    )
    assert preflight.connected is True
    assert [probe.bucket for probe in probes] == ["originals", "results"]
    assert StorageFeature.VERSIONING in preflight.capabilities.features
    assert StorageFeature.LIFECYCLE not in preflight.capabilities.features


def test_provider_preflight_blocks_when_any_required_bucket_is_unreachable():
    class OneMissing(FakeS3):
        def head_bucket(self, *, Bucket):
            if Bucket == "results":
                raise RuntimeError("missing")
            return {}

    profile = StorageConnectionProfile(
        provider_id="vast",
        provider_type=ProviderType.VAST_S3,
        endpoint="https://vast.example",
    )
    preflight, _ = preflight_existing_buckets(
        profile, OneMissing(), buckets=["originals", "results"]
    )
    assert preflight.usable is False
    assert "bucket-unreachable:results" in preflight.blockers
