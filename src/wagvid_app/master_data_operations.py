"""Audited organization-scoped master-data mutations."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Gymnast, MediaAsset, Routine


class GymnastMergeError(ValueError):
    """Raised when two gymnast profiles cannot be merged without ambiguity."""


@dataclass(frozen=True)
class GymnastMergeResult:
    survivor_id: str
    duplicate_id: str
    routines_moved: int
    media_moved: int
    kiga_id_transferred: bool


@transaction.atomic
def merge_gymnasts(*, organization, survivor_id, duplicate_id, actor, reason: str) -> GymnastMergeResult:
    """Merge a duplicate profile into a canonical survivor without deleting history."""
    if str(survivor_id) == str(duplicate_id):
        raise GymnastMergeError("En gymnast kan ikke flettes med sig selv.")
    reason = reason.strip()
    if not reason:
        raise GymnastMergeError("En begrundelse er påkrævet ved sammenfletning.")

    locked = {
        str(item.id): item
        for item in Gymnast.objects.select_for_update()
        .filter(organization=organization, id__in=[survivor_id, duplicate_id])
        .select_related("level")
    }
    survivor = locked.get(str(survivor_id))
    duplicate = locked.get(str(duplicate_id))
    if survivor is None or duplicate is None:
        raise GymnastMergeError("Begge gymnastprofiler skal tilhøre den aktive organisation.")
    if survivor.archived_at is not None:
        raise GymnastMergeError("Den profil der bevares skal være aktiv.")
    if duplicate.archived_at is not None:
        raise GymnastMergeError("Dubletten er allerede arkiveret.")
    if survivor.discipline != duplicate.discipline:
        raise GymnastMergeError("Profiler med forskellig disciplin kan ikke flettes automatisk.")
    if survivor.kiga_id and duplicate.kiga_id and survivor.kiga_id != duplicate.kiga_id:
        raise GymnastMergeError(
            "Profilerne har forskellige KIGA-ID'er. Afklar den eksterne identitet før merge."
        )

    routines_moved = Routine.objects.filter(
        organization=organization, gymnast=duplicate
    ).update(gymnast=survivor)
    media_moved = MediaAsset.objects.filter(
        organization=organization, gymnast=duplicate
    ).update(gymnast=survivor)

    kiga_transferred = False
    if not survivor.kiga_id and duplicate.kiga_id:
        survivor.kiga_id = duplicate.kiga_id
        survivor.save(update_fields=["kiga_id", "updated_at"])
        kiga_transferred = True

    duplicate.archived_at = timezone.now()
    duplicate.save(update_fields=["archived_at", "updated_at"])

    metadata = {
        "survivor_id": str(survivor.id),
        "duplicate_id": str(duplicate.id),
        "duplicate_display_name": duplicate.display_name,
        "duplicate_license_number": duplicate.license_number,
        "routines_moved": routines_moved,
        "media_moved": media_moved,
        "kiga_id_transferred": kiga_transferred,
    }
    organization.audit_events.create(
        actor=actor,
        action="gymnast.merged",
        object_type="gymnast",
        object_id=str(survivor.id),
        reason=reason,
        metadata=metadata,
    )
    organization.audit_events.create(
        actor=actor,
        action="gymnast.merged-into",
        object_type="gymnast",
        object_id=str(duplicate.id),
        reason=reason,
        metadata=metadata,
    )
    return GymnastMergeResult(
        survivor_id=str(survivor.id),
        duplicate_id=str(duplicate.id),
        routines_moved=routines_moved,
        media_moved=media_moved,
        kiga_id_transferred=kiga_transferred,
    )
