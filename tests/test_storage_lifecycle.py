from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.models import (
    Membership,
    Organization,
    StorageBucket,
    StorageConnection,
    StoredObjectRecord,
)
from wagvid_app.secret_refs import EnvironmentSecretResolver, SecretReferenceError
from wagvid_app.storage_lifecycle import (
    apply_storage_connection,
    disconnect_storage_connection,
    preflight_storage_connection,
    preview_deletion,
    quarantine_object,
    reconcile_desired_buckets,
    register_stored_object,
    select_storage_bucket,
    storage_cost_summary,
)
from wagvid_app.wasabi import BucketRole


def connection(organization, name="Primary"):
    return StorageConnection.objects.create(
        organization=organization,
        name=name,
        project_slug="wagvid",
        environment="test",
        region="eu-central-1",
        endpoint="https://s3.eu-central-1.wasabisys.com",
        account_fingerprint="a1b2c3d4",
        access_key_secret_ref="env:WASABI_ACCESS_KEY",
        secret_key_secret_ref="env:WASABI_SECRET_KEY",
        provisioning_enabled=True,
    )


@pytest.mark.django_db
def test_desired_bucket_reconcile_is_idempotent_and_routing_is_stable():
    organization = Organization.objects.create(name="Club", slug="storage-club")
    profile = connection(organization)
    first = reconcile_desired_buckets(profile.id)
    second = reconcile_desired_buckets(profile.id)
    assert {item.id for item in first} == {item.id for item in second}
    assert len(first) == 7
    profile.refresh_from_db()
    selected = select_storage_bucket(
        profile, role=BucketRole.ORIGINALS, routing_key="org/media/sha256"
    )
    repeated = select_storage_bucket(
        profile, role=BucketRole.ORIGINALS, routing_key="org/media/sha256"
    )
    assert selected == repeated
    assert selected.role == BucketRole.ORIGINALS.value


@pytest.mark.django_db
def test_object_registration_sets_billable_until_and_cost_summary():
    organization = Organization.objects.create(name="Club", slug="cost-club")
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    uploaded = datetime(2026, 1, 1, tzinfo=UTC)
    record = register_stored_object(
        organization=organization,
        connection=profile,
        role=BucketRole.ORIGINALS,
        routing_key="video-1",
        object_key="org/originals/video-1.mp4",
        content_sha256="a" * 64,
        size_bytes=10_000_000_000,
        uploaded_at=uploaded,
    )
    assert record.billable_until == uploaded + timedelta(days=90)
    summary = storage_cost_summary(organization)
    assert summary["active_bytes"] == 10_000_000_000
    assert summary["object_count"] == 1


@pytest.mark.django_db
def test_legal_hold_blocks_deletion_and_soft_delete_never_calls_provider():
    organization = Organization.objects.create(name="Club", slug="hold-club")
    admin = User.objects.create_user("storage-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    record = register_stored_object(
        organization=organization,
        connection=profile,
        role=BucketRole.RESULTS,
        routing_key="result-1",
        object_key="org/results/result-1.json",
        content_sha256="b" * 64,
        size_bytes=1_000_000_000,
        uploaded_at=timezone.now(),
    )
    record.legal_hold = True
    record.save(update_fields=["legal_hold"])
    assert preview_deletion(record, requested_at=timezone.now()).blockers == ("legal-hold",)
    with pytest.raises(ValueError, match="legal-hold"):
        quarantine_object(record.id, actor=admin, reason="cleanup")
    record.legal_hold = False
    record.save(update_fields=["legal_hold"])
    preview = quarantine_object(record.id, actor=admin, reason="approved cleanup")
    record.refresh_from_db()
    assert preview.allowed
    assert record.state == StoredObjectRecord.State.QUARANTINED
    assert record.physical_delete_after >= record.billable_until
    assert organization.audit_events.filter(action="storage.object-quarantined").exists()


@pytest.mark.django_db
def test_storage_settings_is_admin_scoped_and_saves_only_secret_references(client):
    organization = Organization.objects.create(name="Club", slug="settings-club")
    admin = User.objects.create_user("settings-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    client.force_login(admin)
    response = client.post(
        reverse("storage-settings"),
        {
            "name": "Wasabi EU",
            "provider": "wasabi",
            "project_slug": "wagvid",
            "environment": "production",
            "region": "eu-central-1",
            "endpoint": "https://s3.eu-central-1.wasabisys.com",
            "tls_verify": "on",
            "addressing_style": "virtual",
            "auth_mode": "access-key",
            "governance_profile": "standard",
            "account_fingerprint": "a1b2c3d4",
            "access_key_secret_ref": "env:WAGVID_WASABI_ACCESS_KEY",
            "secret_key_secret_ref": "env:WAGVID_WASABI_SECRET_KEY",
            "originals_shards": 2,
            "derivatives_shards": 2,
            "include_audit_bucket": "on",
            "enable_versioning": "on",
            "pricing_model": "pay-go",
            "minimum_storage_days": 90,
        },
        follow=True,
    )
    assert response.status_code == 200
    assert "Ingen buckets blev oprettet" in response.content.decode()
    profile = organization.storage_connections.get()
    assert profile.secret_key_secret_ref == "env:WAGVID_WASABI_SECRET_KEY"
    assert profile.status == StorageConnection.Status.CONFIGURED
    assert profile.buckets.count() == 7
    assert organization.audit_events.filter(action="storage.provider-plan-saved").exists()


@pytest.mark.django_db
def test_non_admin_cannot_open_storage_settings(client):
    organization = Organization.objects.create(name="Club", slug="viewer-storage-club")
    viewer = User.objects.create_user("storage-viewer")
    Membership.objects.create(organization=organization, user=viewer, role=Membership.Role.VIEWER)
    client.force_login(viewer)
    assert client.get(reverse("storage-settings")).status_code == 403
    assert StorageBucket.objects.count() == 0


def test_environment_secret_resolver_accepts_only_explicit_available_env_references():
    resolver = EnvironmentSecretResolver({"WAGVID_WASABI_KEY": "sensitive-value"})
    assert resolver.resolve("env:WAGVID_WASABI_KEY") == "sensitive-value"
    with pytest.raises(SecretReferenceError, match="Only env"):
        resolver.resolve("vault:wasabi/key")
    with pytest.raises(SecretReferenceError, match="unavailable"):
        resolver.resolve("env:WAGVID_MISSING_KEY")


@pytest.mark.django_db
def test_preflight_resolves_credentials_at_runtime_and_persists_only_redacted_result():
    organization = Organization.objects.create(name="Club", slug="preflight-club")
    admin = User.objects.create_user("preflight-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    captured = {}

    class EmptyWasabi:
        def list_buckets(self):
            return {"Buckets": []}

    def fake_client_factory(**kwargs):
        captured.update(kwargs)
        return EmptyWasabi()

    resolver = EnvironmentSecretResolver(
        {"WASABI_ACCESS_KEY": "ACCESS-1234", "WASABI_SECRET_KEY": "never-persist-me"}
    )
    result = preflight_storage_connection(
        profile.id, actor=admin, resolver=resolver, client_factory=fake_client_factory
    )
    profile.refresh_from_db()
    assert result.applicable
    assert captured["access_key_id"] == "ACCESS-1234"
    assert captured["secret_access_key"] == "never-persist-me"
    assert profile.status == StorageConnection.Status.VERIFIED
    assert profile.last_preflight["credential_fingerprint"] == "****1234"
    persisted = str(profile.last_preflight)
    assert "ACCESS-1234" not in persisted
    assert "never-persist-me" not in persisted
    assert organization.audit_events.filter(action="storage.provider-preflight").exists()


@pytest.mark.django_db
def test_disconnect_preserves_bucket_and_object_registry():
    organization = Organization.objects.create(name="Club", slug="disconnect-club")
    admin = User.objects.create_user("disconnect-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    profile = connection(organization)
    reconcile_desired_buckets(profile.id)
    register_stored_object(
        organization=organization,
        connection=profile,
        role=BucketRole.RESULTS,
        routing_key="result-preserved",
        object_key="org/results/preserved.json",
        content_sha256="c" * 64,
        size_bytes=1234,
        uploaded_at=timezone.now(),
    )
    bucket_count = profile.buckets.count()
    disconnected = disconnect_storage_connection(
        profile.id, actor=admin, reason="credential rotation"
    )
    assert not disconnected.active
    assert disconnected.status == StorageConnection.Status.DISCONNECTED
    assert StorageBucket.objects.filter(connection=profile).count() == bucket_count
    assert StoredObjectRecord.objects.filter(connection=profile).count() == 1
    event = organization.audit_events.get(action="storage.provider-disconnected")
    assert event.metadata == {"buckets_deleted": False, "objects_deleted": False}


@pytest.mark.django_db
def test_apply_repreflights_requires_typed_approval_and_marks_buckets_ready():
    organization = Organization.objects.create(name="Club", slug="apply-club")
    admin = User.objects.create_user("apply-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    profile = connection(organization)
    profile.provisioning_enabled = True
    profile.save(update_fields=["provisioning_enabled"])
    reconcile_desired_buckets(profile.id)

    class ProvisioningClient:
        def __init__(self):
            self.names = set()
            self.versioned = set()

        def list_buckets(self):
            return {"Buckets": [{"Name": name} for name in self.names]}

        def create_bucket(self, **kwargs):
            self.names.add(kwargs["Bucket"])
            return {}

        def put_bucket_versioning(self, **kwargs):
            self.versioned.add(kwargs["Bucket"])
            return {}

    provider = ProvisioningClient()
    resolver = EnvironmentSecretResolver(
        {"WASABI_ACCESS_KEY": "ACCESS", "WASABI_SECRET_KEY": "SECRET"}
    )
    with pytest.raises(ValueError, match="explicit"):
        apply_storage_connection(
            profile.id,
            actor=admin,
            confirmation="yes",
            resolver=resolver,
            client_factory=lambda **kwargs: provider,
        )
    completed = apply_storage_connection(
        profile.id,
        actor=admin,
            confirmation="CREATE PRIVATE STORAGE BUCKETS",
        resolver=resolver,
        client_factory=lambda **kwargs: provider,
    )
    profile.refresh_from_db()
    assert completed
    assert provider.names == set(profile.buckets.values_list("bucket_name", flat=True))
    assert profile.buckets.exclude(state=StorageBucket.State.READY).count() == 0
    assert profile.status == StorageConnection.Status.VERIFIED
    assert organization.audit_events.filter(action="storage.provider-applied").exists()
