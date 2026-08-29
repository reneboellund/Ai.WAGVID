import hashlib
import io
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from wagvid_app.models import (
    Membership,
    Organization,
    StorageBucket,
    StorageConnection,
    StoredObjectRecord,
)
from wagvid_app.secret_refs import EnvironmentSecretResolver
from wagvid_app.storage_lifecycle import claim_due_deletions, reconcile_desired_buckets
from wagvid_app.wasabi import BucketRole
from wagvid_app.wasabi_data import execute_claimed_deletion, upload_registered_object


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3Data:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise MissingObject
        value = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(value["body"]),
            "Metadata": value["metadata"],
            "VersionId": value["version"],
            "ETag": '"etag"',
        }

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "body": kwargs["Body"].read(),
            "metadata": kwargs["Metadata"],
            "version": "v1",
        }
        self.calls.append(("put", kwargs))
        return {"VersionId": "v1", "ETag": '"etag"'}

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))


def connection(organization):
    return StorageConnection.objects.create(
        organization=organization,
        name="Primary",
        project_slug="wagvid",
        environment="test",
        region="eu-central-1",
        endpoint="https://s3.eu-central-1.wasabisys.com",
        account_fingerprint="a1b2c3d4",
        access_key_secret_ref="env:WASABI_ACCESS_KEY",
        secret_key_secret_ref="env:WASABI_SECRET_KEY",
    )


def factory_for(client):
    def factory(**kwargs):
        assert kwargs["access_key_id"] == "ACCESS"
        assert kwargs["secret_access_key"] == "SECRET"
        return client

    return factory


@pytest.mark.django_db
def test_verified_upload_is_routed_and_registered_with_provider_version():
    organization = Organization.objects.create(name="Club", slug="data-club")
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    profile.buckets.update(state=StorageBucket.State.READY)
    client = FakeS3Data()
    payload = b"competition video"
    digest = hashlib.sha256(payload).hexdigest()
    record = upload_registered_object(
        organization=organization,
        connection=profile,
        role=BucketRole.ORIGINALS,
        routing_key="routine-1",
        object_key="org/routines/routine-1/original.mp4",
        source=io.BytesIO(payload),
        expected_size=len(payload),
        expected_sha256=digest,
        content_type="video/mp4",
        resolver=EnvironmentSecretResolver(
            {"WASABI_ACCESS_KEY": "ACCESS", "WASABI_SECRET_KEY": "SECRET"}
        ),
        client_factory=factory_for(client),
    )
    assert record.version_id == "v1"
    assert record.bucket.state == StorageBucket.State.READY
    assert record.content_sha256 == digest
    assert organization.audit_events.filter(action="storage.object-uploaded").exists()


@pytest.mark.django_db
def test_due_deletion_claim_is_hold_safe_and_provider_failure_is_retryable():
    organization = Organization.objects.create(name="Club", slug="delete-worker-club")
    admin = User.objects.create_user("delete-worker-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    profile.buckets.update(state=StorageBucket.State.READY)
    now = timezone.now()
    bucket = profile.buckets.filter(role=BucketRole.RESULTS.value).get()
    record = StoredObjectRecord.objects.create(
        organization=organization,
        connection=profile,
        bucket=bucket,
        object_key="org/result.json",
        version_id="version-1",
        role=BucketRole.RESULTS.value,
        content_sha256="d" * 64,
        size_bytes=123,
        uploaded_at=now - timedelta(days=100),
        billable_until=now - timedelta(days=10),
        state=StoredObjectRecord.State.QUARANTINED,
        physical_delete_after=now - timedelta(minutes=1),
        deletion_reason="retention completed",
    )
    held = StoredObjectRecord.objects.create(
        organization=organization,
        connection=profile,
        bucket=bucket,
        object_key="org/held.json",
        version_id="version-2",
        role=BucketRole.RESULTS.value,
        content_sha256="e" * 64,
        size_bytes=123,
        uploaded_at=now - timedelta(days=100),
        billable_until=now - timedelta(days=10),
        state=StoredObjectRecord.State.QUARANTINED,
        physical_delete_after=now - timedelta(minutes=1),
        legal_hold=True,
    )
    claimed = claim_due_deletions(now=now)
    assert claimed == (record,)
    held.refresh_from_db()
    assert held.state == StoredObjectRecord.State.QUARANTINED

    failing = FakeS3Data()
    failing.delete_object = lambda **kwargs: (_ for _ in ()).throw(ConnectionError("offline"))
    resolver = EnvironmentSecretResolver(
        {"WASABI_ACCESS_KEY": "ACCESS", "WASABI_SECRET_KEY": "SECRET"}
    )
    with pytest.raises(ConnectionError):
        execute_claimed_deletion(
            claimed[0],
            resolver=resolver,
            client_factory=factory_for(failing),
        )
    record.refresh_from_db()
    assert record.state == StoredObjectRecord.State.QUARANTINED
    assert organization.audit_events.filter(action="storage.object-delete-failed").exists()

    claimed = claim_due_deletions(now=now)
    assert claimed == (record,)
    successful = FakeS3Data()
    execute_claimed_deletion(
        claimed[0], actor=admin, resolver=resolver, client_factory=factory_for(successful)
    )
    record.refresh_from_db()
    assert record.state == StoredObjectRecord.State.DELETED
    assert successful.calls[-1][1]["VersionId"] == "version-1"
    assert organization.audit_events.filter(action="storage.object-physically-deleted").exists()
