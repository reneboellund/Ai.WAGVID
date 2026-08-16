from datetime import UTC, datetime, timedelta

import pytest

from wagvid_app.wasabi import WasabiCostPolicy, WasabiLayoutConfig, build_setup_plan
from wagvid_app.wasabi_provider import (
    SetupApproval,
    WasabiSetupError,
    apply_setup,
    run_preflight,
)


class FakeS3:
    def __init__(self, buckets=None, *, deny=False):
        self.buckets = buckets or {}
        self.deny = deny
        self.calls = []

    def list_buckets(self):
        if self.deny:
            raise PermissionError
        return {"Buckets": [{"Name": name} for name in self.buckets]}

    def get_bucket_location(self, *, Bucket):
        return {"LocationConstraint": self.buckets[Bucket]["region"]}

    def get_bucket_acl(self, *, Bucket):
        uri = "http://acs.amazonaws.com/groups/global/AllUsers"
        return {"Grants": [{"Grantee": {"URI": uri}}]} if self.buckets[Bucket].get("public") else {"Grants": []}

    def get_bucket_versioning(self, *, Bucket):
        return {"Status": self.buckets[Bucket].get("versioning")}

    def create_bucket(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {}

    def put_bucket_versioning(self, **kwargs):
        self.calls.append(("versioning", kwargs))
        return {}


def plan():
    config = WasabiLayoutConfig("wagvid", "test", "a1b2c3d4", "eu-central-1", 1, 1, False)
    return build_setup_plan(config, WasabiCostPolicy())


def test_preflight_redacts_key_and_plans_missing_buckets_without_mutation():
    client = FakeS3()
    result = run_preflight(client, plan=plan(), access_key_id="WASABIACCESS1234")
    assert result.credential_fingerprint == "****1234"
    assert result.applicable
    assert any(action.action == "create-private-bucket" for action in result.actions)
    assert client.calls == []


def test_preflight_fails_closed_on_denied_or_public_bucket():
    denied = run_preflight(FakeS3(deny=True), plan=plan(), access_key_id="key")
    assert not denied.applicable
    desired = plan().buckets[0]
    public = FakeS3({desired.name: {"region": desired.region, "public": True, "versioning": "Enabled"}})
    result = run_preflight(public, plan=plan(), access_key_id="key")
    assert not result.applicable
    assert any(action.action == "block-public-bucket" for action in result.actions)


def test_apply_requires_matching_unexpired_explicit_approval():
    desired = plan()
    client = FakeS3()
    preflight = run_preflight(client, plan=desired, access_key_id="key")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    approval = SetupApproval(
        desired.digest, "admin", now, now + timedelta(minutes=5),
        "CREATE PRIVATE WASABI BUCKETS",
    )
    completed = apply_setup(client, plan=desired, preflight=preflight, approval=approval, now=now)
    assert completed
    assert len(client.calls) == len(preflight.actions)
    expired = SetupApproval(
        desired.digest, "admin", now, now + timedelta(seconds=1),
        "CREATE PRIVATE WASABI BUCKETS",
    )
    with pytest.raises(WasabiSetupError, match="expired"):
        apply_setup(
            FakeS3(), plan=desired, preflight=preflight,
            approval=expired, now=now + timedelta(seconds=2),
        )
