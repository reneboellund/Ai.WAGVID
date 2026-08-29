"""Event-level KIGA export and durable notification outbox."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .kiga_exports import export_kiga_routine
from .models import Event, KigaNotification, Membership


def event_export(event: Event) -> dict:
    rows, excluded = [], []
    for routine in event.routines.select_related("event", "gymnast").prefetch_related(
        "external_media_references", "official_versions", "media__analysis_jobs__result"
    ):
        try:
            rows.append(export_kiga_routine(routine))
        except ValueError as error:
            excluded.append({"routine_id": str(routine.id), "reason": str(error)})
    payload = {
        "schema": "ai.wagvid.kiga-event-export.v1",
        "event_id": str(event.id),
        "external_event_id": event.external_id or None,
        "created_at": timezone.now().isoformat(),
        "rows": rows,
        "excluded": excluded,
    }
    payload["export_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


@transaction.atomic
def queue_notification(*, event: Event, actor, destination_ref: str, idempotency_key: str = ""):
    allowed = {
        Membership.Role.SYSTEM_ADMIN,
        Membership.Role.ORGANIZATION_ADMIN,
        Membership.Role.OPERATOR,
    }
    if not actor.wagvid_memberships.filter(
        organization=event.organization, active=True, role__in=allowed
    ).exists():
        raise PermissionError("KIGA export operator role is required")
    destination_ref = destination_ref.strip()
    if not destination_ref.startswith(("secret:", "env:", "vault:")):
        raise ValueError("destination must be a configured secret/reference, not a raw URL")
    export = event_export(event)
    seed = idempotency_key.strip() or f"{event.id}:{export['export_digest']}:{destination_ref}"
    key = hashlib.sha256(seed.encode()).hexdigest()
    payload = {
        "schema": "ai.wagvid.kiga-notification.v1",
        "event_type": "analysis.batch-ready",
        "destination_ref": destination_ref,
        "event_id": str(event.id),
        "export_digest": export["export_digest"],
        "export_url_name": "kiga-event-export",
    }
    item, created = KigaNotification.objects.get_or_create(
        organization=event.organization,
        idempotency_key=key,
        defaults={
            "event": event,
            "destination_ref": destination_ref,
            "export_digest": export["export_digest"],
            "payload": payload,
            "requested_by": actor,
        },
    )
    if created:
        event.organization.audit_events.create(
            actor=actor,
            action="kiga.notification-queued",
            object_type="kiga-notification",
            object_id=str(item.id),
            metadata={"event_id": str(event.id), "export_digest": export["export_digest"]},
        )
    return item, created
