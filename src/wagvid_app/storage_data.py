"""Provider-neutral orchestration between S3 operations and the object ledger."""

from __future__ import annotations

from datetime import datetime
from typing import BinaryIO

from django.utils import timezone

from .models import Organization, StorageBucket, StorageConnection, StoredObjectRecord
from .s3_clients import create_profile_client
from .s3_storage import S3ObjectStore
from .secret_refs import EnvironmentSecretResolver
from .storage_lifecycle import (
    complete_physical_deletion,
    register_stored_object,
    release_failed_deletion,
    resolve_storage_connection,
    select_storage_bucket,
)
from .storage_types import BucketRole


def _client(connection, *, resolver, client_factory):
    if client_factory is None:
        return create_profile_client(connection, resolver=resolver)
    return client_factory(
        access_key_id=resolver.resolve(connection.access_key_secret_ref),
        secret_access_key=resolver.resolve(connection.secret_key_secret_ref),
        region=connection.region,
        endpoint=connection.endpoint,
    )


def upload_registered_object(
    *,
    organization: Organization,
    role: BucketRole,
    routing_key: str,
    object_key: str,
    source: BinaryIO,
    expected_size: int,
    expected_sha256: str,
    connection: StorageConnection | None = None,
    content_type: str = "application/octet-stream",
    retention_until: datetime | None = None,
    actor=None,
    resolver=None,
    client_factory=None,
) -> StoredObjectRecord:
    connection = connection or resolve_storage_connection(organization, role=role)
    if connection.organization_id != organization.id or not connection.active:
        raise ValueError("an active organization storage connection is required")
    bucket = select_storage_bucket(connection, role=role, routing_key=routing_key)
    if bucket.state != StorageBucket.State.READY:
        raise ValueError("selected S3 bucket is not ready")
    resolver = resolver or EnvironmentSecretResolver()
    stored = S3ObjectStore(
        _client(connection, resolver=resolver, client_factory=client_factory),
        bucket=bucket.bucket_name,
    ).put_verified(
        object_key,
        source,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
        content_type=content_type,
    )
    record = register_stored_object(
        organization=organization,
        connection=connection,
        role=role,
        routing_key=routing_key,
        object_key=object_key,
        content_sha256=stored.sha256,
        size_bytes=stored.size,
        uploaded_at=timezone.now(),
        retention_until=retention_until,
        version_id=stored.version_id,
    )
    organization.audit_events.create(
        actor=actor,
        action="storage.object-uploaded",
        object_type="stored-object",
        object_id=str(record.id),
        metadata={
            "provider": connection.provider,
            "bucket": bucket.bucket_name,
            "size_bytes": stored.size,
            "role": role.value,
        },
    )
    return record


def execute_claimed_deletion(
    record: StoredObjectRecord,
    *,
    actor=None,
    resolver=None,
    client_factory=None,
) -> StoredObjectRecord:
    record = StoredObjectRecord.objects.select_related("connection", "bucket").get(pk=record.pk)
    if record.state != StoredObjectRecord.State.PENDING_DELETE:
        raise ValueError("deletion record must be claimed before provider execution")
    if not record.version_id:
        release_failed_deletion(record.id, error_code="missing-version-id")
        raise ValueError("versioned deletion requires a registered version ID")
    resolver = resolver or EnvironmentSecretResolver()
    try:
        S3ObjectStore(
            _client(record.connection, resolver=resolver, client_factory=client_factory),
            bucket=record.bucket.bucket_name,
        ).delete_version(record.object_key, version_id=record.version_id)
    except Exception as error:
        release_failed_deletion(record.id, error_code=type(error).__name__[:80])
        raise
    return complete_physical_deletion(record.id, actor=actor)
