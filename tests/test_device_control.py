import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.device_operations import (
    DeviceOperationError,
    acknowledge_device_command,
    claim_pairing_offer,
    create_pairing_offer,
    enqueue_device_command,
    poll_device_commands,
)
from wagvid_app.models import Device, DeviceCommand, Gymnast, Level, Membership, Organization


def setup_admin():
    user = User.objects.create_user("device-admin", password="secret")
    organization = Organization.objects.create(name="Device Club", slug="device-club")
    Membership.objects.create(
        user=user, organization=organization, role=Membership.Role.ORGANIZATION_ADMIN
    )
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Ada",
        license_number="DEVICE-1",
    )
    return user, organization, gymnast


def pair(user, organization):
    offer = create_pairing_offer(organization=organization, requested_by=user)
    grant = claim_pairing_offer(
        session_id=offer.session.id,
        code=offer.code,
        device_key="android-installation-1",
        device_name="Tripod phone",
        app_version="0.1.0",
    )
    return grant


@pytest.mark.django_db
def test_pairing_is_short_lived_single_use_and_token_is_hashed():
    user, organization, _ = setup_admin()
    offer = create_pairing_offer(organization=organization, requested_by=user)
    with pytest.raises(DeviceOperationError, match="invalid pairing"):
        claim_pairing_offer(
            session_id=offer.session.id,
            code="000000" if offer.code != "000000" else "999999",
            device_key="phone-x",
            device_name="Phone",
            app_version="1",
        )
    grant = claim_pairing_offer(
        session_id=offer.session.id,
        code=offer.code,
        device_key="phone-x",
        device_name="Phone",
        app_version="1",
    )
    assert grant.device.check_api_token(grant.api_token)
    assert grant.api_token not in grant.device.api_token_hash
    with pytest.raises(DeviceOperationError, match="consumed"):
        claim_pairing_offer(
            session_id=offer.session.id,
            code=offer.code,
            device_key="phone-y",
            device_name="Phone 2",
            app_version="1",
        )


@pytest.mark.django_db
def test_pairing_locks_after_five_wrong_codes():
    user, organization, _ = setup_admin()
    offer = create_pairing_offer(organization=organization, requested_by=user)
    wrong = "000000" if offer.code != "000000" else "999999"
    for _ in range(5):
        with pytest.raises(DeviceOperationError, match="invalid pairing"):
            claim_pairing_offer(
                session_id=offer.session.id,
                code=wrong,
                device_key="brute-force-phone",
                device_name="Phone",
                app_version="1",
            )
    with pytest.raises(DeviceOperationError, match="expired"):
        claim_pairing_offer(
            session_id=offer.session.id,
            code=offer.code,
            device_key="brute-force-phone",
            device_name="Phone",
            app_version="1",
        )
@pytest.mark.django_db
def test_command_delivery_acknowledgement_and_idempotency_follow_state_machine():
    user, organization, gymnast = setup_admin()
    grant = pair(user, organization)
    payload = {
        "capture_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "gymnast_id": str(gymnast.id),
        "kind": "drill",
    }
    item, created = enqueue_device_command(
        device_id=grant.device.id,
        requested_by=user,
        command=DeviceCommand.Command.START,
        idempotency_key="start-1",
        payload=payload,
    )
    repeated, repeated_created = enqueue_device_command(
        device_id=grant.device.id,
        requested_by=user,
        command=DeviceCommand.Command.START,
        idempotency_key="start-1",
        payload=payload,
    )
    assert created and not repeated_created and repeated.id == item.id
    delivered = poll_device_commands(grant.device.id)
    assert delivered[0].state == DeviceCommand.State.DELIVERED
    accepted = acknowledge_device_command(
        command_id=item.id,
        device_id=grant.device.id,
        accepted=True,
        resulting_state=Device.State.RECORDING,
        rejection_code="",
    )
    grant.device.refresh_from_db()
    assert accepted.state == DeviceCommand.State.ACCEPTED
    assert grant.device.state == Device.State.RECORDING
    assert organization.audit_events.filter(action="device.command-acknowledged").exists()


@pytest.mark.django_db
def test_command_rejection_expiry_and_cross_state_protection():
    user, organization, gymnast = setup_admin()
    grant = pair(user, organization)
    item, _ = enqueue_device_command(
        device_id=grant.device.id,
        requested_by=user,
        command=DeviceCommand.Command.ARM,
        idempotency_key="arm-1",
        payload={"gymnast_id": str(gymnast.id), "kind": "training"},
    )
    rejected = acknowledge_device_command(
        command_id=item.id,
        device_id=grant.device.id,
        accepted=False,
        resulting_state=Device.State.READY,
        rejection_code="CAMERA_PERMISSION_DENIED",
    )
    assert rejected.state == DeviceCommand.State.REJECTED

    item, _ = enqueue_device_command(
        device_id=grant.device.id,
        requested_by=user,
        command=DeviceCommand.Command.START,
        idempotency_key="start-expired",
        payload={"gymnast_id": str(gymnast.id), "kind": "training"},
    )
    DeviceCommand.objects.filter(pk=item.id).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert poll_device_commands(grant.device.id) == []
    item.refresh_from_db()
    assert item.state == DeviceCommand.State.EXPIRED


@pytest.mark.django_db
def test_pair_heartbeat_command_and_ack_api_end_to_end(client):
    user, _, gymnast = setup_admin()
    client.force_login(user)
    pairing = client.post(reverse("device-pairing-create"))
    assert pairing.status_code == 201
    claim = client.post(
        reverse("device-pairing-claim", args=[pairing.json()["pairing_id"]]),
        json.dumps(
            {
                "code": pairing.json()["code"],
                "device_key": "api-phone-1",
                "device_name": "API phone",
                "app_version": "0.1",
            }
        ),
        content_type="application/json",
    )
    assert claim.status_code == 201
    headers = {
        "HTTP_X_WAGVID_DEVICE": claim.json()["device_key"],
        "HTTP_AUTHORIZATION": f"Bearer {claim.json()['api_token']}",
    }
    heartbeat = client.post(
        reverse("device-heartbeat"),
        json.dumps(
            {
                "state": "ready",
                "battery_percent": 87,
                "free_storage_bytes": 5_000_000,
                "queued_uploads": 2,
                "network_type": "wifi",
                "app_version": "0.1",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert heartbeat.status_code == 200
    device = Device.objects.get(pk=claim.json()["device_id"])
    command = client.post(
        reverse("device-command-create", args=[device.id]),
        json.dumps(
            {
                "command": "start",
                "idempotency_key": "api-start-1",
                "payload": {"gymnast_id": str(gymnast.id), "kind": "drill"},
            }
        ),
        content_type="application/json",
    )
    assert command.status_code == 201
    polled = client.get(reverse("device-command-poll"), **headers)
    assert polled.json()["commands"][0]["command"] == "start"
    context = client.get(reverse("device-capture-context"), **headers)
    assert context.status_code == 200
    assert context.json()["gymnasts"][0]["license_number"] == "DEVICE-1"
    ack = client.post(
        reverse("device-command-ack", args=[command.json()["command_id"]]),
        json.dumps({"accepted": True, "resulting_state": "recording"}),
        content_type="application/json",
        **headers,
    )
    assert ack.status_code == 200
    device.refresh_from_db()
    assert device.battery_percent == 87 and device.state == Device.State.RECORDING


@pytest.mark.django_db
def test_admin_webui_creates_pairing_offer_and_remote_capture_command(client):
    user, organization, gymnast = setup_admin()
    grant = pair(user, organization)
    client.force_login(user)
    pairing_page = client.post(reverse("devices"))
    assert pairing_page.status_code == 200
    assert "Pairingkode" in pairing_page.content.decode()

    response = client.post(
        reverse("operate"),
        {
            "device_id": str(grant.device.id),
            "gymnast_id": str(gymnast.id),
            "kind": "training",
            "apparatus": "BB",
            "command": "arm",
            "idempotency_key": "web-arm-1",
        },
    )
    assert response.status_code == 302
    command = grant.device.commands.get(idempotency_key="web-arm-1")
    assert command.payload["gymnast_id"] == str(gymnast.id)
    assert command.payload["apparatus"] == "BB"


@pytest.mark.django_db
def test_non_admin_webui_cannot_pair_or_control_device(client):
    user, organization, gymnast = setup_admin()
    grant = pair(user, organization)
    membership = user.wagvid_memberships.get()
    membership.role = Membership.Role.COACH
    membership.save()
    client.force_login(user)
    assert client.post(reverse("devices")).status_code == 403
    response = client.post(
        reverse("operate"),
        {
            "device_id": str(grant.device.id),
            "gymnast_id": str(gymnast.id),
            "kind": "drill",
            "command": "start",
        },
    )
    assert response.status_code == 403
    assert grant.device.commands.count() == 0
