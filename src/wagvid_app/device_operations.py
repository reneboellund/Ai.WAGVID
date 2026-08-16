"""Authenticated Android pairing, telemetry and remote-command operations."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ai_wagvid.capture import CaptureCommand, CaptureMode, CaptureSession, CaptureState

from .models import (
    Device,
    DeviceCommand,
    DevicePairingSession,
    Gymnast,
    MediaAsset,
    Membership,
    Organization,
)


class DeviceOperationError(ValueError):
    pass


@dataclass(frozen=True)
class PairingOffer:
    session: DevicePairingSession
    code: str


@dataclass(frozen=True)
class PairingGrant:
    device: Device
    api_token: str


def _can_administer(user, organization: Organization) -> bool:
    return user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN],
    ).exists()


@transaction.atomic
def create_pairing_offer(
    *, organization: Organization, requested_by, lifetime_seconds: int = 300
) -> PairingOffer:
    if not _can_administer(requested_by, organization):
        raise PermissionError("Organization administrator role is required")
    if not 60 <= lifetime_seconds <= 900:
        raise DeviceOperationError("pairing lifetime must be between 60 and 900 seconds")
    code = f"{secrets.randbelow(1_000_000):06d}"
    session = DevicePairingSession.objects.create(
        organization=organization,
        requested_by=requested_by,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=lifetime_seconds),
    )
    organization.audit_events.create(
        actor=requested_by,
        action="device.pairing-created",
        object_type="device-pairing-session",
        object_id=str(session.id),
        metadata={"expires_at": session.expires_at.isoformat()},
    )
    return PairingOffer(session, code)


def claim_pairing_offer(
    *, session_id: UUID, code: str, device_key: str, device_name: str, app_version: str
) -> PairingGrant:
    session = DevicePairingSession.objects.get(pk=session_id)
    if session.consumed_at or session.expires_at <= timezone.now() or session.failed_attempts >= 5:
        raise DeviceOperationError("pairing offer is expired or already consumed")
    if not check_password(code, session.code_hash):
        DevicePairingSession.objects.filter(pk=session.id).update(
            failed_attempts=F("failed_attempts") + 1
        )
        raise DeviceOperationError("invalid pairing code")
    if not device_key or len(device_key) > 160 or not device_name:
        raise DeviceOperationError("device identity is invalid")
    with transaction.atomic():
        session = DevicePairingSession.objects.select_for_update().get(pk=session_id)
        if (
            session.consumed_at
            or session.expires_at <= timezone.now()
            or session.failed_attempts >= 5
        ):
            raise DeviceOperationError("pairing offer is expired or already consumed")
        if Device.objects.filter(device_key=device_key).exists():
            raise DeviceOperationError("device key is already paired")
        raw_token = secrets.token_urlsafe(32)
        device = Device(
            organization=session.organization,
            name=device_name[:120],
            device_key=device_key,
            state=Device.State.READY,
            last_seen_at=timezone.now(),
            app_version=app_version[:80],
        )
        device.set_api_token(raw_token)
        device.save()
        session.device = device
        session.consumed_at = timezone.now()
        session.save(update_fields=["device", "consumed_at", "updated_at"])
        session.organization.audit_events.create(
            action="device.paired",
            object_type="device",
            object_id=str(device.id),
            metadata={"device_key": device.device_key, "app_version": device.app_version},
        )
    return PairingGrant(device, raw_token)


@transaction.atomic
def update_device_heartbeat(
    device_id: UUID,
    *,
    state: str,
    battery_percent: int | None,
    free_storage_bytes: int | None,
    queued_uploads: int,
    network_type: str,
    app_version: str,
    active_capture_id: UUID | None,
) -> Device:
    device = Device.objects.select_for_update().get(pk=device_id)
    if state not in Device.State.values or state == Device.State.UNPAIRED:
        raise DeviceOperationError("invalid paired device state")
    if battery_percent is not None and not 0 <= battery_percent <= 100:
        raise DeviceOperationError("battery percent must be between 0 and 100")
    if free_storage_bytes is not None and free_storage_bytes < 0:
        raise DeviceOperationError("free storage cannot be negative")
    if queued_uploads < 0:
        raise DeviceOperationError("queued uploads cannot be negative")
    device.state = state
    device.battery_percent = battery_percent
    device.free_storage_bytes = free_storage_bytes
    device.queued_uploads = queued_uploads
    device.network_type = network_type[:40]
    device.app_version = app_version[:80]
    device.active_capture_id = active_capture_id
    device.last_seen_at = timezone.now()
    device.save(
        update_fields=[
            "state",
            "battery_percent",
            "free_storage_bytes",
            "queued_uploads",
            "network_type",
            "app_version",
            "active_capture_id",
            "last_seen_at",
            "updated_at",
        ]
    )
    return device


def _capture_transition(device: Device, command: str, *, actor: str) -> CaptureSession:
    session = CaptureSession(state=CaptureState(device.state))
    mode = CaptureMode.MOTION if command == DeviceCommand.Command.ARM else None
    return session.apply(CaptureCommand(command), actor=actor, mode=mode)


@transaction.atomic
def enqueue_device_command(
    *,
    device_id: UUID,
    requested_by,
    command: str,
    idempotency_key: str,
    payload: dict,
    lifetime_seconds: int = 60,
) -> tuple[DeviceCommand, bool]:
    device = Device.objects.select_for_update().select_related("organization").get(pk=device_id)
    if not _can_administer(requested_by, device.organization):
        raise PermissionError("Organization administrator role is required")
    if command not in DeviceCommand.Command.values:
        raise DeviceOperationError("unknown device command")
    if not idempotency_key or len(idempotency_key) > 160:
        raise DeviceOperationError("idempotency key is required")
    existing = device.commands.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.command != command or existing.payload != payload:
            raise DeviceOperationError("idempotency key was reused with different command data")
        return existing, False
    if not 10 <= lifetime_seconds <= 300:
        raise DeviceOperationError("command lifetime must be between 10 and 300 seconds")
    if command in {DeviceCommand.Command.START, DeviceCommand.Command.ARM}:
        gymnast_id = payload.get("gymnast_id")
        kind = payload.get("kind")
        if not gymnast_id or kind not in MediaAsset.Kind.values:
            raise DeviceOperationError("capture command requires gymnast_id and valid kind")
        if not Gymnast.objects.filter(
            pk=gymnast_id, organization=device.organization, archived_at__isnull=True
        ).exists():
            raise DeviceOperationError("gymnast is not active in the device organization")
    _capture_transition(device, command, actor=f"admin:{requested_by.pk}")
    item = DeviceCommand.objects.create(
        organization=device.organization,
        device=device,
        command=command,
        expected_device_state=device.state,
        payload=payload,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        expires_at=timezone.now() + timedelta(seconds=lifetime_seconds),
    )
    device.organization.audit_events.create(
        actor=requested_by,
        action="device.command-enqueued",
        object_type="device-command",
        object_id=str(item.id),
        metadata={"device_id": str(device.id), "command": command},
    )
    return item, True


@transaction.atomic
def poll_device_commands(device_id: UUID, *, limit: int = 10) -> list[DeviceCommand]:
    now = timezone.now()
    DeviceCommand.objects.filter(
        device_id=device_id,
        state__in=[DeviceCommand.State.PENDING, DeviceCommand.State.DELIVERED],
        expires_at__lte=now,
    ).update(state=DeviceCommand.State.EXPIRED)
    commands = list(
        DeviceCommand.objects.select_for_update()
        .filter(
            device_id=device_id,
            state__in=[DeviceCommand.State.PENDING, DeviceCommand.State.DELIVERED],
            expires_at__gt=now,
        )
        .order_by("created_at")[: max(1, min(limit, 50))]
    )
    pending_ids = [item.id for item in commands if item.state == DeviceCommand.State.PENDING]
    DeviceCommand.objects.filter(id__in=pending_ids).update(
        state=DeviceCommand.State.DELIVERED, delivered_at=now
    )
    for item in commands:
        if item.id in pending_ids:
            item.state = DeviceCommand.State.DELIVERED
            item.delivered_at = now
    return commands


@transaction.atomic
def acknowledge_device_command(
    *, command_id: UUID, device_id: UUID, accepted: bool, resulting_state: str, rejection_code: str
) -> DeviceCommand:
    item = (
        DeviceCommand.objects.select_for_update()
        .select_related("device__organization")
        .get(pk=command_id, device_id=device_id)
    )
    if item.state in {DeviceCommand.State.ACCEPTED, DeviceCommand.State.REJECTED}:
        return item
    if item.state == DeviceCommand.State.EXPIRED or item.expires_at <= timezone.now():
        raise DeviceOperationError("command has expired")
    device = item.device
    if accepted:
        if device.state != item.expected_device_state:
            raise DeviceOperationError("device state changed before command acknowledgement")
        expected = _capture_transition(device, item.command, actor=f"admin:{item.requested_by_id}")
        if resulting_state != expected.state.value:
            raise DeviceOperationError("reported resulting state does not match the command")
        item.state = DeviceCommand.State.ACCEPTED
        device.state = resulting_state
        device.save(update_fields=["state", "updated_at"])
    else:
        if not rejection_code:
            raise DeviceOperationError("rejected command requires a rejection code")
        item.state = DeviceCommand.State.REJECTED
        item.rejection_code = rejection_code[:100]
    item.acknowledged_at = timezone.now()
    item.save(update_fields=["state", "rejection_code", "acknowledged_at", "updated_at"])
    device.organization.audit_events.create(
        action="device.command-acknowledged",
        object_type="device-command",
        object_id=str(item.id),
        metadata={"accepted": accepted, "resulting_state": resulting_state},
    )
    return item
