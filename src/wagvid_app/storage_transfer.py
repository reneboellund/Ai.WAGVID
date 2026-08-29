"""Audited, checksum-verified cross-provider object transfer workflow."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import StorageBucket, StorageTransfer, StoredObjectRecord
from .s3_clients import create_profile_client
from .s3_storage import S3ObjectStore
from .secret_refs import EnvironmentSecretResolver
from .storage_layout import StorageCostPolicy
from .storage_lifecycle import select_storage_bucket
from .storage_providers import ObjectLocation
from .storage_types import BucketRole


def object_location(record: StoredObjectRecord) -> ObjectLocation:
    return ObjectLocation(
        record.connection.provider,
        str(record.connection_id),
        record.bucket.bucket_name,
        record.object_key,
        record.version_id,
    )


@transaction.atomic
def plan_storage_transfer(
    *,
    source: StoredObjectRecord,
    target_connection,
    role: BucketRole,
    routing_key: str,
    target_key: str,
    client_request_id: str,
    actor,
) -> tuple[StorageTransfer, bool]:
    if source.organization_id != target_connection.organization_id or not target_connection.active:
        raise ValueError("source and target must belong to the same organization")
    if not client_request_id or len(client_request_id) > 160:
        raise ValueError("bounded transfer request ID is required")
    if not actor.wagvid_memberships.filter(
        organization=source.organization,
        active=True,
        role__in=["organization-admin", "system-admin"],
    ).exists():
        raise PermissionError("administrator role is required")
    bucket = select_storage_bucket(target_connection, role=role, routing_key=routing_key)
    if bucket.state != StorageBucket.State.READY:
        raise ValueError("target storage bucket is not ready")
    existing = StorageTransfer.objects.filter(
        organization=source.organization, client_request_id=client_request_id
    ).first()
    if existing:
        if (
            existing.source_object_id != source.id
            or existing.target_connection_id != target_connection.id
            or existing.target_key != target_key
        ):
            raise ValueError("transfer request ID was reused with different parameters")
        return existing, False
    transfer = StorageTransfer.objects.create(
        organization=source.organization,
        source_object=source,
        target_connection=target_connection,
        target_bucket=bucket,
        target_key=target_key,
        expected_sha256=source.content_sha256,
        expected_size_bytes=source.size_bytes,
        client_request_id=client_request_id,
    )
    source.organization.audit_events.create(
        actor=actor,
        action="storage.transfer-planned",
        object_type="storage-transfer",
        object_id=str(transfer.id),
        metadata={
            "source": object_location(source).__dict__,
            "target_provider": target_connection.provider,
            "target_bucket": bucket.bucket_name,
            "target_key": target_key,
            "source_delete": False,
        },
    )
    return transfer, True


def _client(connection, resolver, client_factory):
    return (
        client_factory(connection)
        if client_factory
        else create_profile_client(connection, resolver=resolver)
    )


def execute_storage_transfer(
    transfer_id,
    *,
    actor,
    resolver=None,
    client_factory=None,
) -> StorageTransfer:
    with transaction.atomic():
        transfer = (
            StorageTransfer.objects.select_for_update()
            .select_related(
                "organization",
                "source_object__connection",
                "source_object__bucket",
                "target_connection",
                "target_bucket",
            )
            .get(pk=transfer_id)
        )
        if transfer.state == StorageTransfer.State.COMPLETED:
            return transfer
        if transfer.state not in {StorageTransfer.State.PLANNED, StorageTransfer.State.FAILED}:
            raise ValueError("storage transfer is not retryable in its current state")
        transfer.state = StorageTransfer.State.COPYING
        transfer.error_code = ""
        transfer.save(update_fields=["state", "error_code", "updated_at"])
    resolver = resolver or EnvironmentSecretResolver()
    source = transfer.source_object
    source_store = S3ObjectStore(
        _client(source.connection, resolver, client_factory), bucket=source.bucket.bucket_name
    )
    target_store = S3ObjectStore(
        _client(transfer.target_connection, resolver, client_factory),
        bucket=transfer.target_bucket.bucket_name,
    )
    try:
        stream = source_store.open_read(source.object_key, version_id=source.version_id)
        stored = target_store.put_verified(
            transfer.target_key,
            stream,
            expected_size=transfer.expected_size_bytes,
            expected_sha256=transfer.expected_sha256,
        )
        verified = target_store.inspect(transfer.target_key)
        if verified.size != transfer.expected_size_bytes or verified.sha256 != transfer.expected_sha256:
            raise ValueError("target verification differs from transfer manifest")
    except Exception as error:
        with transaction.atomic():
            failed = StorageTransfer.objects.select_for_update().get(pk=transfer.id)
            failed.state = StorageTransfer.State.FAILED
            failed.error_code = type(error).__name__[:80]
            failed.save(update_fields=["state", "error_code", "updated_at"])
            failed.organization.audit_events.create(
                actor=actor,
                action="storage.transfer-failed",
                object_type="storage-transfer",
                object_id=str(failed.id),
                metadata={"error_code": failed.error_code},
            )
        raise
    with transaction.atomic():
        completed = StorageTransfer.objects.select_for_update().get(pk=transfer.id)
        completed.state = StorageTransfer.State.VERIFYING
        completed.save(update_fields=["state", "updated_at"])
        policy = StorageCostPolicy(
            completed.target_connection.pricing_model,
            completed.target_connection.minimum_storage_days,
        )
        now = timezone.now()
        StoredObjectRecord.objects.get_or_create(
            connection=completed.target_connection,
            bucket=completed.target_bucket,
            object_key=completed.target_key,
            version_id=stored.version_id,
            defaults={
                "organization": completed.organization,
                "role": completed.target_bucket.role,
                "content_sha256": stored.sha256,
                "size_bytes": stored.size,
                "uploaded_at": now,
                "billable_until": policy.billable_until(now),
            },
        )
        completed.target_version_id = stored.version_id
        completed.bytes_copied = stored.size
        completed.state = StorageTransfer.State.COMPLETED
        completed.save(
            update_fields=["target_version_id", "bytes_copied", "state", "updated_at"]
        )
        completed.organization.audit_events.create(
            actor=actor,
            action="storage.transfer-completed",
            object_type="storage-transfer",
            object_id=str(completed.id),
            metadata={"sha256": stored.sha256, "source_deleted": False},
        )
    return completed
