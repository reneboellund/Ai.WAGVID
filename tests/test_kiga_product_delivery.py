import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from test_kiga_import import record, setup_org

from wagvid_app.kiga import commit_kiga_record, preview_kiga_record
from wagvid_app.kiga_delivery import event_export, queue_notification
from wagvid_app.models import KigaNotification, Membership, Organization


@pytest.mark.django_db
def test_event_export_is_traceable_and_excludes_unready_routines():
    _, organization = setup_org()
    preview = preview_kiga_record(organization, json.dumps(record()))
    event, routine, _, _ = commit_kiga_record(organization, preview)
    payload = event_export(event)
    assert payload["schema"] == "ai.wagvid.kiga-event-export.v1"
    assert len(payload["export_digest"]) == 64
    assert payload["rows"][0]["routine"]["external_id"] == routine.external_id
    assert payload["rows"][0]["rights"]["training_allowed"] is False
    assert "raw_model" not in json.dumps(payload)


@pytest.mark.django_db
def test_notification_outbox_is_idempotent_and_requires_reference_destination():
    user, organization = setup_org()
    event, _, _, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(record()))
    )
    first, created = queue_notification(
        event=event, actor=user, destination_ref="secret:kiga/webhook", idempotency_key="one"
    )
    second, duplicated = queue_notification(
        event=event, actor=user, destination_ref="secret:kiga/webhook", idempotency_key="one"
    )
    assert created is True and duplicated is False and first.id == second.id
    assert first.state == KigaNotification.State.PENDING
    assert organization.audit_events.filter(action="kiga.notification-queued").count() == 1
    with pytest.raises(ValueError, match="raw URL"):
        queue_notification(event=event, actor=user, destination_ref="https://example.invalid/hook")


@pytest.mark.django_db
def test_kiga_event_export_and_notification_buttons_work_in_gui(client):
    user, organization = setup_org()
    event, _, _, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(record()))
    )
    client.force_login(user)
    page = client.get(reverse("competitions"))
    assert page.status_code == 200
    body = page.content.decode()
    assert reverse("kiga-event-export", args=[event.id]) in body
    assert reverse("kiga-notification-queue", args=[event.id]) in body
    exported = client.get(reverse("kiga-event-export", args=[event.id]))
    assert exported.status_code == 200
    assert exported["Cache-Control"] == "private, no-store"
    queued = client.post(
        reverse("kiga-notification-queue", args=[event.id]),
        {"destination_ref": "vault:kiga/webhook", "idempotency_key": "ui-one"},
    )
    assert queued.status_code == 302
    assert organization.kiga_notifications.count() == 1


@pytest.mark.django_db
def test_kiga_delivery_is_role_and_organization_scoped(client):
    _, organization = setup_org()
    event, _, _, _ = commit_kiga_record(
        organization, preview_kiga_record(organization, json.dumps(record()))
    )
    other = Organization.objects.create(name="Other", slug="kiga-delivery-other")
    outsider = User.objects.create_user("kiga-delivery-outsider")
    Membership.objects.create(user=outsider, organization=other, role=Membership.Role.OPERATOR)
    client.force_login(outsider)
    assert client.get(reverse("kiga-event-export", args=[event.id])).status_code == 404
    assert client.post(
        reverse("kiga-notification-queue", args=[event.id]),
        {"destination_ref": "secret:kiga/webhook"},
    ).status_code == 404
