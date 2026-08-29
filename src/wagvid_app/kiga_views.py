from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .kiga_delivery import event_export, queue_notification
from .models import Event
from .organization_context import active_organization


@login_required
def kiga_event_export(request, event_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    payload = event_export(event)
    organization.audit_events.create(
        actor=request.user, action="kiga.event-exported", object_type="event",
        object_id=str(event.id), metadata={"export_digest": payload["export_digest"]},
    )
    response = JsonResponse(payload)
    response["Content-Disposition"] = f'attachment; filename="wagvid-kiga-event-{event.id}.json"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def kiga_notification_queue(request, event_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    event = get_object_or_404(Event, pk=event_id, organization=organization)
    try:
        _, created = queue_notification(
            event=event, actor=request.user,
            destination_ref=request.POST.get("destination_ref", ""),
            idempotency_key=request.POST.get("idempotency_key", ""),
        )
    except PermissionError:
        return HttpResponseForbidden()
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "KIGA-notifikationen er lagt i outbox." if created else "Den samme KIGA-notifikation findes allerede.")
    return redirect("competitions")
