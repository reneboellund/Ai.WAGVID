"""Persisted provider-neutral desired state, routing and cost-aware deletion workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Organization,
    StorageBucket,
    StorageConnection,
    StorageRoleAssignment,
    StoredObjectRecord,
)
from .secret_refs import EnvironmentSecretResolver
from .storage_layout import StorageCostPolicy, build_storage_layout
from .storage_providers import evaluate_capabilities, provider_definition
from .storage_types import BucketRole, route_object
from .wasabi_provider import (
    SetupApproval,
    WasabiSetupError,
    apply_setup,
    create_boto3_client,
    run_preflight,
)


def connection_plan(connection: StorageConnection):
    return build_storage_layout(connection, provider_definition(connection.provider))


@transaction.atomic
def reconcile_desired_buckets(connection_id) -> tuple[StorageBucket, ...]:
    connection = StorageConnection.objects.select_for_update().get(pk=connection_id)
    plan = connection_plan(connection)
    buckets = []
    for item in plan.buckets:
        bucket, _ = StorageBucket.objects.update_or_create(
            connection=connection,
            role=item.role.value,
            shard=item.shard,
            routing_revision=connection.routing_revision,
            defaults={
                "bucket_name": item.name,
                "region": item.region,
                "private": item.private,
                "versioning": item.versioning,
                "object_lock": item.object_lock,
                "state": StorageBucket.State.DESIRED,
            },
        )
        buckets.append(bucket)
    StorageBucket.objects.filter(
        connection=connection, routing_revision=connection.routing_revision
    ).exclude(pk__in=[bucket.pk for bucket in buckets]).update(state=StorageBucket.State.RETIRED)
    connection.desired_plan_digest = plan.digest
    connection.status = StorageConnection.Status.CONFIGURED
    connection.save(update_fields=["desired_plan_digest", "status", "updated_at"])
    return tuple(buckets)


def select_storage_bucket(
    connection: StorageConnection, *, role: BucketRole, routing_key: str,
) -> StorageBucket:
    persisted = tuple(
        connection.buckets.filter(
            role=role.value,
            routing_revision=connection.routing_revision,
            state__in=[StorageBucket.State.DESIRED, StorageBucket.State.READY],
        ).order_by("shard")
    )
    desired_by_name = {
        item.name: item
        for item in connection_plan(connection).buckets
        if item.role is role
    }
    selected = route_object(
        role=role,
        routing_key=routing_key,
        buckets=tuple(desired_by_name[item.bucket_name] for item in persisted),
    )
    return next(item for item in persisted if item.bucket_name == selected.name)


@transaction.atomic
def assign_storage_role(
    *, organization: Organization, role: BucketRole, connection: StorageConnection, actor
) -> StorageRoleAssignment:
    if connection.organization_id != organization.id or not connection.active:
        raise ValueError("storage role requires an active organization connection")
    if not actor.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=["organization-admin", "system-admin"],
    ).exists():
        raise PermissionError("administrator role is required")
    if not connection.buckets.filter(
        role=role.value,
        routing_revision=connection.routing_revision,
    ).exists():
        raise ValueError(f"connection has no bucket mapping for role {role.value}")
    assignment, _ = StorageRoleAssignment.objects.update_or_create(
        organization=organization,
        role=role.value,
        defaults={"connection": connection, "active": True},
    )
    organization.audit_events.create(
        actor=actor,
        action="storage.role-assigned",
        object_type="storage-role-assignment",
        object_id=str(assignment.id),
        metadata={"role": role.value, "connection_id": str(connection.id)},
    )
    return assignment


def resolve_storage_connection(
    organization: Organization, *, role: BucketRole
) -> StorageConnection:
    assignment = (
        organization.storage_role_assignments.filter(
            role=role.value, active=True, connection__active=True
        )
        .select_related("connection")
        .first()
    )
    if not assignment:
        raise LookupError(f"no active storage provider assigned for role {role.value}")
    return assignment.connection


@transaction.atomic
def register_stored_object(
    *, organization: Organization, connection: StorageConnection, role: BucketRole,
    routing_key: str, object_key: str, content_sha256: str, size_bytes: int,
    uploaded_at: datetime, retention_until: datetime | None = None, version_id: str = "",
) -> StoredObjectRecord:
    if connection.organization_id != organization.id:
        raise ValueError("storage connection does not belong to organization")
    if (
        len(content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in content_sha256)
        or size_bytes < 0
    ):
        raise ValueError("stored object requires lowercase SHA-256 and non-negative size")
    if retention_until and retention_until < uploaded_at:
        raise ValueError("retention cannot end before upload")
    bucket = select_storage_bucket(connection, role=role, routing_key=routing_key)
    policy = StorageCostPolicy(connection.pricing_model, connection.minimum_storage_days)
    return StoredObjectRecord.objects.create(
        organization=organization,
        connection=connection,
        bucket=bucket,
        object_key=object_key,
        version_id=version_id,
        role=role.value,
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        uploaded_at=uploaded_at,
        billable_until=policy.billable_until(uploaded_at),
        retention_until=retention_until,
    )


@dataclass(frozen=True)
class DeletionPreview:
    object_id: str
    allowed: bool
    physical_delete_after: datetime | None
    early_delete_gb_days: Decimal
    blockers: tuple[str, ...]


def preview_deletion(record: StoredObjectRecord, *, requested_at: datetime) -> DeletionPreview:
    blockers = []
    if record.legal_hold:
        blockers.append("legal-hold")
    if record.retention_until and requested_at < record.retention_until:
        blockers.append("retention-active")
    policy = StorageCostPolicy(
        record.connection.pricing_model, record.connection.minimum_storage_days
    )
    exposure = Decimal(str(policy.early_delete_exposure_gb_days(
        size_bytes=record.size_bytes,
        uploaded_at=record.uploaded_at,
        delete_at=requested_at,
    )))
    physical_after = max(
        requested_at + timedelta(days=7),
        record.billable_until,
        record.retention_until or requested_at,
    )
    return DeletionPreview(
        str(record.id), not blockers, physical_after if not blockers else None,
        exposure, tuple(blockers),
    )


@transaction.atomic
def quarantine_object(record_id, *, actor, reason: str) -> DeletionPreview:
    record = (
        StoredObjectRecord.objects.select_for_update()
        .select_related("connection", "organization")
        .get(pk=record_id)
    )
    if not reason.strip() or record.state != StoredObjectRecord.State.ACTIVE:
        raise ValueError("active object and deletion reason are required")
    if not actor.wagvid_memberships.filter(
        organization=record.organization,
        active=True,
        role__in=["organization-admin", "system-admin"],
    ).exists():
        raise PermissionError("administrator role is required")
    now = timezone.now()
    preview = preview_deletion(record, requested_at=now)
    if not preview.allowed:
        raise ValueError("object deletion is blocked: " + ", ".join(preview.blockers))
    record.state = StoredObjectRecord.State.QUARANTINED
    record.delete_requested_at = now
    record.physical_delete_after = preview.physical_delete_after
    record.deletion_reason = reason.strip()
    record.save(update_fields=[
        "state", "delete_requested_at", "physical_delete_after", "deletion_reason", "updated_at"
    ])
    record.organization.audit_events.create(
        actor=actor,
        action="storage.object-quarantined",
        object_type="stored-object",
        object_id=str(record.id),
        reason=reason.strip(),
        metadata={
            "bucket": record.bucket.bucket_name,
            "physical_delete_after": preview.physical_delete_after.isoformat(),
            "early_delete_gb_days": str(preview.early_delete_gb_days),
        },
    )
    return preview


def storage_cost_summary(organization: Organization) -> dict[str, int | str]:
    records = organization.stored_objects.exclude(state=StoredObjectRecord.State.DELETED)
    active = records.filter(state=StoredObjectRecord.State.ACTIVE)
    pending = records.exclude(state=StoredObjectRecord.State.ACTIVE)
    now = timezone.now()
    exposure = Decimal(0)
    for record in records.filter(billable_until__gt=now).select_related("connection"):
        exposure += Decimal(str(StorageCostPolicy(
            record.connection.pricing_model, record.connection.minimum_storage_days
        ).early_delete_exposure_gb_days(
            size_bytes=record.size_bytes,
            uploaded_at=record.uploaded_at,
            delete_at=now,
        )))
    return {
        "active_bytes": active.aggregate(total=Sum("size_bytes"))["total"] or 0,
        "pending_delete_bytes": pending.aggregate(total=Sum("size_bytes"))["total"] or 0,
        "early_delete_exposure_gb_days": str(exposure.quantize(Decimal("0.001"))),
        "object_count": records.count(),
    }


def _require_storage_admin(connection: StorageConnection, actor) -> None:
    if not actor.wagvid_memberships.filter(
        organization=connection.organization,
        active=True,
        role__in=["organization-admin", "system-admin"],
    ).exists():
        raise PermissionError("administrator role is required")


@transaction.atomic
def preflight_storage_connection(
    connection_id,
    *,
    actor,
    resolver=None,
    client_factory=create_boto3_client,
):
    connection = (
        StorageConnection.objects.select_for_update()
        .select_related("organization")
        .get(pk=connection_id)
    )
    _require_storage_admin(connection, actor)
    resolver = resolver or EnvironmentSecretResolver()
    access_key = resolver.resolve(connection.access_key_secret_ref)
    secret_key = resolver.resolve(connection.secret_key_secret_ref)
    plan = connection_plan(connection)
    client = client_factory(
        access_key_id=access_key,
        secret_access_key=secret_key,
        region=connection.region,
        endpoint=connection.endpoint,
    )
    result = run_preflight(client, plan=plan, access_key_id=access_key)
    support_state, capability_issues = evaluate_capabilities(
        connection.provider,
        connection.governance_profile,
        connection.capability_snapshot.get("verified", {}),
    )
    connection.last_preflight = {
        "endpoint": result.endpoint,
        "region": result.region,
        "credential_fingerprint": result.credential_fingerprint,
        "can_list_buckets": result.can_list_buckets,
        "applicable": result.applicable,
        "errors": list(result.errors),
        "plan_digest": result.plan_digest,
        "actions": [
            {
                "action": item.action,
                "bucket": item.bucket,
                "details": item.details,
                "destructive": item.destructive,
            }
            for item in result.actions
        ],
        "provider": connection.provider,
        "support_state": support_state,
        "capability_issues": list(capability_issues),
    }
    connection.last_preflight_at = timezone.now()
    connection.support_state = support_state
    connection.status = (
        StorageConnection.Status.VERIFIED
        if result.applicable and support_state == "validated"
        else StorageConnection.Status.DEGRADED
    )
    connection.save(
        update_fields=[
            "last_preflight", "last_preflight_at", "support_state", "status", "updated_at"
        ]
    )
    connection.organization.audit_events.create(
        actor=actor,
        action="storage.provider-preflight",
        object_type="storage-connection",
        object_id=str(connection.id),
        metadata={
            "applicable": result.applicable,
            "plan_digest": result.plan_digest,
            "action_count": len(result.actions),
            "credential_fingerprint": result.credential_fingerprint,
        },
    )
    return result


def apply_storage_connection(
    connection_id,
    *,
    actor,
    confirmation: str,
    resolver=None,
    client_factory=create_boto3_client,
) -> tuple[str, ...]:
    """Re-preflight and apply one exact desired-state plan after typed approval."""

    connection = StorageConnection.objects.select_related("organization").get(pk=connection_id)
    _require_storage_admin(connection, actor)
    if confirmation != "CREATE PRIVATE STORAGE BUCKETS":
        raise ValueError("explicit object-storage setup confirmation is required")
    resolver = resolver or EnvironmentSecretResolver()
    access_key = resolver.resolve(connection.access_key_secret_ref)
    client = client_factory(
        access_key_id=access_key,
        secret_access_key=resolver.resolve(connection.secret_key_secret_ref),
        region=connection.region,
        endpoint=connection.endpoint,
    )
    plan = connection_plan(connection)
    if not plan.provisioning_enabled:
        raise WasabiSetupError("bucket provisioning is disabled for this connection")
    preflight = run_preflight(client, plan=plan, access_key_id=access_key)
    now = timezone.now()
    approval = SetupApproval(
        plan.digest,
        str(actor.id),
        now,
        now + timedelta(minutes=5),
        confirmation,
    )
    try:
        completed = apply_setup(
            client, plan=plan, preflight=preflight, approval=approval, now=now
        )
    except Exception as error:
        with transaction.atomic():
            locked = StorageConnection.objects.select_for_update().get(pk=connection.id)
            locked.status = StorageConnection.Status.DEGRADED
            locked.save(update_fields=["status", "updated_at"])
            locked.organization.audit_events.create(
                actor=actor,
                action="storage.provider-apply-failed",
                object_type="storage-connection",
                object_id=str(locked.id),
                metadata={"error_code": type(error).__name__[:80], "plan_digest": plan.digest},
            )
        raise WasabiSetupError(f"provider apply failed: {type(error).__name__}") from error
    with transaction.atomic():
        locked = StorageConnection.objects.select_for_update().get(pk=connection.id)
        if locked.desired_plan_digest != plan.digest:
            raise WasabiSetupError("stored setup plan changed during provider apply")
        locked.buckets.filter(routing_revision=locked.routing_revision).update(
            state=StorageBucket.State.READY
        )
        locked.status = StorageConnection.Status.VERIFIED
        locked.save(update_fields=["status", "updated_at"])
        locked.organization.audit_events.create(
            actor=actor,
            action="storage.provider-applied",
            object_type="storage-connection",
            object_id=str(locked.id),
            metadata={
                "plan_digest": plan.digest,
                "completed_actions": list(completed),
                "bucket_count": locked.buckets.filter(
                    routing_revision=locked.routing_revision
                ).count(),
            },
        )
    return completed


@transaction.atomic
def disconnect_storage_connection(connection_id, *, actor, reason: str) -> StorageConnection:
    connection = (
        StorageConnection.objects.select_for_update()
        .select_related("organization")
        .get(pk=connection_id)
    )
    _require_storage_admin(connection, actor)
    if not reason.strip():
        raise ValueError("disconnect reason is required")
    connection.active = False
    connection.status = StorageConnection.Status.DISCONNECTED
    connection.save(update_fields=["active", "status", "updated_at"])
    connection.organization.audit_events.create(
        actor=actor,
        action="storage.provider-disconnected",
        object_type="storage-connection",
        object_id=str(connection.id),
        reason=reason.strip(),
        metadata={"buckets_deleted": False, "objects_deleted": False},
    )
    return connection


@transaction.atomic
def claim_due_deletions(*, now: datetime, limit: int = 50) -> tuple[StoredObjectRecord, ...]:
    """Move eligible quarantined records to a retry-safe provider work state."""

    if limit < 1 or limit > 500:
        raise ValueError("deletion claim limit must be between 1 and 500")
    candidates = list(
        StoredObjectRecord.objects.select_for_update()
        .filter(
            state=StoredObjectRecord.State.QUARANTINED,
            physical_delete_after__lte=now,
            legal_hold=False,
        )
        .filter(models.Q(retention_until__isnull=True) | models.Q(retention_until__lte=now))
        .select_related("connection", "bucket", "organization")
        .order_by("physical_delete_after")[:limit]
    )
    for record in candidates:
        record.state = StoredObjectRecord.State.PENDING_DELETE
        record.save(update_fields=["state", "updated_at"])
    return tuple(candidates)


@transaction.atomic
def complete_physical_deletion(record_id, *, actor=None) -> StoredObjectRecord:
    record = (
        StoredObjectRecord.objects.select_for_update()
        .select_related("organization", "bucket")
        .get(pk=record_id)
    )
    if record.state != StoredObjectRecord.State.PENDING_DELETE:
        raise ValueError("only a claimed deletion can be completed")
    record.state = StoredObjectRecord.State.DELETED
    record.save(update_fields=["state", "updated_at"])
    record.organization.audit_events.create(
        actor=actor,
        action="storage.object-physically-deleted",
        object_type="stored-object",
        object_id=str(record.id),
        metadata={
            "bucket": record.bucket.bucket_name,
            "object_key": record.object_key,
            "version_id": record.version_id,
        },
    )
    return record


@transaction.atomic
def release_failed_deletion(record_id, *, error_code: str) -> StoredObjectRecord:
    """Return a failed provider operation to quarantine without storing secret error text."""

    record = StoredObjectRecord.objects.select_for_update().select_related("organization").get(
        pk=record_id
    )
    if record.state != StoredObjectRecord.State.PENDING_DELETE:
        raise ValueError("only a claimed deletion can be released")
    if not error_code or len(error_code) > 80:
        raise ValueError("bounded provider error code is required")
    record.state = StoredObjectRecord.State.QUARANTINED
    record.save(update_fields=["state", "updated_at"])
    record.organization.audit_events.create(
        action="storage.object-delete-failed",
        object_type="stored-object",
        object_id=str(record.id),
        metadata={"error_code": error_code},
    )
    return record
