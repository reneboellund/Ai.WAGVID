import hashlib
import io
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from wagvid_app.forms import StorageConnectionForm
from wagvid_app.models import (
    Membership,
    Organization,
    StorageBucket,
    StorageConnection,
    StorageTransfer,
    StoredObjectRecord,
)
from wagvid_app.s3_clients import create_profile_client
from wagvid_app.storage_contract import StorageContractReport
from wagvid_app.storage_layout import build_storage_layout
from wagvid_app.storage_lifecycle import (
    assign_storage_role,
    reconcile_desired_buckets,
    resolve_storage_connection,
)
from wagvid_app.storage_providers import (
    PROVIDERS,
    CapabilityState,
    StorageCapability,
    evaluate_capabilities,
    provider_definition,
)
from wagvid_app.storage_transfer import execute_storage_transfer, plan_storage_transfer
from wagvid_app.wasabi import BucketRole


def profile(provider_id, **overrides):
    values = {
        "provider": provider_id,
        "project_slug": "wagvid",
        "environment": "production",
        "account_fingerprint": "a1b2c3d4",
        "region": "eu-central-1",
        "endpoint": "https://s3.example.internal",
        "originals_shards": 2,
        "derivatives_shards": 2,
        "include_audit_bucket": True,
        "enable_versioning": True,
        "existing_bucket_map": {},
        "governance_profile": "standard",
        "tls_verify": True,
        "custom_ca_secret_ref": "",
        "pricing_model": "pay-go" if provider_id == "wasabi" else "none",
        "minimum_storage_days": 90 if provider_id == "wasabi" else 0,
        "provisioning_enabled": provider_id != "ootbi-s3",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_catalog_has_five_capability_first_provider_profiles():
    assert set(PROVIDERS) == {"wasabi", "aws-s3", "ontap-s3", "vast-s3", "ootbi-s3"}
    assert all(set(item.capabilities) == set(StorageCapability) for item in PROVIDERS.values())
    assert provider_definition("aws-s3").default_addressing_style == "virtual"
    assert provider_definition("ontap-s3").default_addressing_style == "path"
    assert provider_definition("vast-s3").capabilities[StorageCapability.OBJECT_LOCK] == CapabilityState.PROBE
    assert provider_definition("ootbi-s3").existing_bucket_only


def test_governance_fails_closed_on_unsupported_or_unverified_features():
    state, issues = evaluate_capabilities("ontap-s3", "evidence-immutable")
    assert state == "limited"
    assert any("object-lock" in issue for issue in issues)
    state, issues = evaluate_capabilities(
        "ontap-s3",
        "evidence-immutable",
        {"versioning": "supported", "object-lock": "unsupported"},
    )
    assert state == "incompatible"
    state, issues = evaluate_capabilities("aws-s3", "evidence-immutable")
    assert state == "validated" and not issues


@pytest.mark.parametrize("provider_id", ["wasabi", "aws-s3", "ontap-s3", "vast-s3"])
def test_common_bounded_layout_works_without_provider_specific_media_logic(provider_id):
    plan = build_storage_layout(profile(provider_id), provider_definition(provider_id))
    assert plan.provider_id == provider_id
    assert len(plan.buckets) == 7
    assert {item.role for item in plan.buckets} == set(BucketRole)
    assert len(plan.digest) == 64


def test_ootbi_is_existing_bucket_only_and_skips_transient_derivatives():
    connection = profile(
        "ootbi-s3",
        existing_bucket_map={"originals": ["ootbi-evidence-a", "ootbi-evidence-b"], "audit": "ootbi-audit"},
    )
    plan = build_storage_layout(connection, provider_definition("ootbi-s3"))
    assert not plan.provisioning_enabled
    assert {item.role for item in plan.buckets} == {BucketRole.ORIGINALS, BucketRole.AUDIT}
    assert all(item.role is not BucketRole.DERIVATIVES for item in plan.buckets)


@pytest.mark.django_db
def test_storage_form_enforces_tls_auth_and_provider_specific_provisioning():
    common = {
        "name": "Storage",
        "project_slug": "wagvid",
        "environment": "production",
        "region": "eu-central-1",
        "endpoint": "http://storage.internal",
        "tls_verify": False,
        "addressing_style": "path",
        "auth_mode": "workload-identity",
        "account_fingerprint": "a1b2c3d4",
        "originals_shards": 1,
        "derivatives_shards": 1,
        "governance_profile": "standard",
        "pricing_model": "none",
        "minimum_storage_days": 0,
        "provisioning_enabled": True,
    }
    form = StorageConnectionForm({**common, "provider": "ootbi-s3"})
    assert not form.is_valid()
    assert {"endpoint", "tls_verify", "auth_mode", "provisioning_enabled"} <= set(form.errors)
    aws = StorageConnectionForm(
        {
            **common,
            "provider": "aws-s3",
            "endpoint": "https://s3.eu-central-1.amazonaws.com",
            "tls_verify": True,
            "addressing_style": "virtual",
        }
    )
    assert aws.is_valid(), aws.errors


@pytest.mark.django_db
def test_logical_roles_can_route_to_different_provider_connections(client):
    organization = Organization.objects.create(name="Club", slug="multi-provider-club")
    admin = User.objects.create_user("provider-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    wasabi = StorageConnection.objects.create(
        organization=organization,
        name="Wasabi originals",
        provider="wasabi",
        endpoint="https://s3.eu-central-1.wasabisys.com",
        region="eu-central-1",
        account_fingerprint="a1b2c3d4",
        access_key_secret_ref="env:WASABI_ACCESS_KEY",
        secret_key_secret_ref="env:WASABI_SECRET_KEY",
    )
    aws = StorageConnection.objects.create(
        organization=organization,
        name="AWS results",
        provider="aws-s3",
        endpoint="https://s3.eu-central-1.amazonaws.com",
        region="eu-central-1",
        account_fingerprint="e5f6a7b8",
        auth_mode="workload-identity",
        pricing_model="none",
        minimum_storage_days=0,
    )
    reconcile_desired_buckets(wasabi.id)
    reconcile_desired_buckets(aws.id)
    assign_storage_role(
        organization=organization, role=BucketRole.ORIGINALS, connection=wasabi, actor=admin
    )
    assign_storage_role(
        organization=organization, role=BucketRole.RESULTS, connection=aws, actor=admin
    )
    assert resolve_storage_connection(organization, role=BucketRole.ORIGINALS) == wasabi
    assert resolve_storage_connection(organization, role=BucketRole.RESULTS) == aws
    assert organization.audit_events.filter(action="storage.role-assigned").count() == 2
    client.force_login(admin)
    page = client.get(reverse("storage-settings"))
    assert page.status_code == 200
    assert b"Wasabi originals" in page.content and b"AWS results" in page.content


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class TransferFake:
    def __init__(self):
        self.objects = {}

    def head_object(self, *, Bucket, Key):
        try:
            value = self.objects[(Bucket, Key)]
        except KeyError as error:
            raise MissingObject from error
        return {
            "ContentLength": len(value["body"]),
            "Metadata": value["metadata"],
            "VersionId": value["version"],
            "ETag": '"etag"',
        }

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "body": kwargs["Body"].read(), "metadata": kwargs["Metadata"], "version": "target-v1"
        }
        return {"VersionId": "target-v1", "ETag": '"etag"'}

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])]["body"])}


@pytest.mark.django_db
def test_cross_provider_transfer_is_planned_idempotent_verified_and_non_destructive():
    organization = Organization.objects.create(name="Club", slug="transfer-club")
    admin = User.objects.create_user("transfer-admin")
    Membership.objects.create(
        organization=organization, user=admin, role=Membership.Role.ORGANIZATION_ADMIN
    )
    source_connection = StorageConnection.objects.create(
        organization=organization, name="Source", provider="wasabi",
        endpoint="https://s3.eu-central-1.wasabisys.com", region="eu-central-1",
        account_fingerprint="a1b2c3d4", access_key_secret_ref="env:SOURCE_KEY",
        secret_key_secret_ref="env:SOURCE_SECRET",
    )
    target_connection = StorageConnection.objects.create(
        organization=organization, name="Target", provider="aws-s3",
        endpoint="https://s3.eu-central-1.amazonaws.com", region="eu-central-1",
        account_fingerprint="e5f6a7b8", auth_mode="workload-identity",
        pricing_model="none", minimum_storage_days=0,
    )
    reconcile_desired_buckets(source_connection.id)
    reconcile_desired_buckets(target_connection.id)
    source_connection.buckets.update(state=StorageBucket.State.READY)
    target_connection.buckets.update(state=StorageBucket.State.READY)
    payload = b"immutable evidence"
    digest = hashlib.sha256(payload).hexdigest()
    source_bucket = source_connection.buckets.filter(role=BucketRole.ORIGINALS.value).first()
    source_record = StoredObjectRecord.objects.create(
        organization=organization, connection=source_connection, bucket=source_bucket,
        object_key="org/source.mp4", version_id="source-v1", role=BucketRole.ORIGINALS.value,
        content_sha256=digest, size_bytes=len(payload), uploaded_at="2026-01-01T00:00:00Z",
        billable_until="2026-04-01T00:00:00Z",
    )
    transfer, created = plan_storage_transfer(
        source=source_record, target_connection=target_connection, role=BucketRole.ORIGINALS,
        routing_key="routine-1", target_key="org/copied.mp4", client_request_id="move-1",
        actor=admin,
    )
    repeated, repeated_created = plan_storage_transfer(
        source=source_record, target_connection=target_connection, role=BucketRole.ORIGINALS,
        routing_key="routine-1", target_key="org/copied.mp4", client_request_id="move-1",
        actor=admin,
    )
    assert created and not repeated_created and repeated == transfer
    source_fake, target_fake = TransferFake(), TransferFake()
    source_fake.objects[(source_bucket.bucket_name, source_record.object_key)] = {
        "body": payload, "metadata": {"sha256": digest}, "version": "source-v1"
    }
    clients = {source_connection.id: source_fake, target_connection.id: target_fake}
    completed = execute_storage_transfer(
        transfer.id, actor=admin, client_factory=lambda connection: clients[connection.id]
    )
    assert completed.state == StorageTransfer.State.COMPLETED
    assert completed.bytes_copied == len(payload)
    assert completed.target_version_id == "target-v1"
    assert source_record.state == StoredObjectRecord.State.ACTIVE
    assert StoredObjectRecord.objects.filter(
        connection=target_connection, object_key="org/copied.mp4", content_sha256=digest
    ).exists()


def test_profile_client_uses_workload_identity_only_for_supported_provider(monkeypatch):
    calls = []

    class Boto:
        @staticmethod
        def client(service, **kwargs):
            calls.append((service, kwargs))
            return object()

    class ConfigModule:
        class Config:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    monkeypatch.setattr(
        "wagvid_app.s3_clients.importlib.import_module",
        lambda name: Boto if name == "boto3" else ConfigModule,
    )
    aws = SimpleNamespace(
        provider="aws-s3", tls_verify=True, environment="production",
        auth_mode="workload-identity", region="eu-central-1",
        endpoint="https://s3.eu-central-1.amazonaws.com", custom_ca_secret_ref="",
        addressing_style="virtual", role_arn="", id="connection-id",
    )
    create_profile_client(aws)
    assert calls[0][0] == "s3"
    assert "aws_access_key_id" not in calls[0][1]
    aws.provider = "ontap-s3"
    with pytest.raises(ValueError, match="workload identity"):
        create_profile_client(aws)


@pytest.mark.django_db
def test_contract_validation_command_requires_opt_in_and_persists_sanitized_report(monkeypatch):
    organization = Organization.objects.create(name="Club", slug="command-probe-club")
    connection = StorageConnection.objects.create(
        organization=organization, name="AWS", provider="aws-s3",
        endpoint="https://s3.eu-central-1.amazonaws.com", region="eu-central-1",
        account_fingerprint="a1b2c3d4", auth_mode="workload-identity",
        pricing_model="none", minimum_storage_days=0,
    )
    with pytest.raises(CommandError, match="approve-test-objects"):
        call_command("validate_storage_provider", str(connection.id), bucket="contract")
    report = StorageContractReport(
        "aws-s3", "contract", "validated",
        {"sigv4": "supported", "range-get": "supported", "multipart": "supported"},
        ("put", "head", "range-get", "multipart-complete"), (),
    )
    monkeypatch.setattr(
        "wagvid_app.management.commands.validate_storage_provider.create_profile_client",
        lambda connection: object(),
    )
    monkeypatch.setattr(
        "wagvid_app.management.commands.validate_storage_provider.run_storage_contract_probe",
        lambda *args, **kwargs: report,
    )
    call_command(
        "validate_storage_provider", str(connection.id), bucket="contract",
        approve_test_objects=True,
    )
    connection.refresh_from_db()
    assert connection.support_state == "validated"
    assert connection.capability_snapshot["verified"]["multipart"] == "supported"
    assert organization.audit_events.filter(action="storage.provider-contract-validated").exists()
