"""Audited master-data archive and duplicate-merge operations."""

from django.db import transaction
from django.utils import timezone

from .models import Gymnast, MediaAsset, Routine, UploadSession


def _require_admin(actor, organization):
    if not actor.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=["organization-admin", "system-admin"],
    ).exists():
        raise PermissionError("administrator role is required")


@transaction.atomic
def archive_gymnast(gymnast_id, *, actor, reason: str) -> Gymnast:
    gymnast = Gymnast.objects.select_for_update().select_related("organization").get(pk=gymnast_id)
    _require_admin(actor, gymnast.organization)
    if not reason.strip():
        raise ValueError("archive reason is required")
    if gymnast.archived_at is None:
        gymnast.archived_at = timezone.now()
        gymnast.save(update_fields=["archived_at", "updated_at"])
        gymnast.organization.audit_events.create(
            actor=actor,
            action="gymnast.archived",
            object_type="gymnast",
            object_id=str(gymnast.id),
            reason=reason.strip(),
        )
    return gymnast


@transaction.atomic
def merge_gymnasts(source_id, target_id, *, actor, reason: str) -> Gymnast:
    if source_id == target_id or not reason.strip():
        raise ValueError("distinct gymnasts and merge reason are required")
    gymnasts = {
        item.id: item
        for item in Gymnast.objects.select_for_update().select_related("organization").filter(
            id__in=[source_id, target_id]
        )
    }
    if set(gymnasts) != {source_id, target_id}:
        raise Gymnast.DoesNotExist
    source, target = gymnasts[source_id], gymnasts[target_id]
    if source.organization_id != target.organization_id:
        raise ValueError("gymnasts must belong to the same organization")
    _require_admin(actor, source.organization)
    Routine.objects.filter(gymnast=source).update(gymnast=target)
    MediaAsset.objects.filter(gymnast=source).update(gymnast=target)
    UploadSession.objects.filter(gymnast=source).update(gymnast=target)
    source.archived_at = timezone.now()
    source.save(update_fields=["archived_at", "updated_at"])
    source.organization.audit_events.create(
        actor=actor,
        action="gymnast.merged",
        object_type="gymnast",
        object_id=str(source.id),
        reason=reason.strip(),
        metadata={"target_gymnast_id": str(target.id)},
    )
    return target
