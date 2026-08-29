"""Persistent, auditable network-camera control-plane operations."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .models import Membership, NetworkCamera, NetworkCameraAction


class CameraOperationError(ValueError):
    pass


def require_camera_operator(actor, organization) -> None:
    roles = {
        Membership.Role.SYSTEM_ADMIN,
        Membership.Role.ORGANIZATION_ADMIN,
        Membership.Role.OPERATOR,
    }
    if not actor.wagvid_memberships.filter(
        organization=organization, active=True, role__in=roles
    ).exists():
        raise PermissionError("camera operator role is required")


def capability_digest(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def apply_capability_snapshot(camera: NetworkCamera, snapshot: dict) -> None:
    if snapshot and snapshot.get("schema") != "ai.wagvid.camera-capabilities.v1":
        raise CameraOperationError("unsupported camera capability schema")
    streams = snapshot.get("streams", []) if snapshot else []
    stream_ids = {str(item.get("profile_id", "")) for item in streams}
    if camera.canonical_profile_id and camera.canonical_profile_id not in stream_ids:
        raise CameraOperationError("canonical stream profile was not discovered")
    if camera.preview_profile_id and camera.preview_profile_id not in stream_ids:
        raise CameraOperationError("preview stream profile was not discovered")
    if camera.canonical_profile_id and camera.preview_profile_id == camera.canonical_profile_id:
        raise CameraOperationError("canonical and preview profiles must be different")
    camera.capability_snapshot = snapshot
    camera.capability_digest = capability_digest(snapshot) if snapshot else ""
    camera.stable_device_id = str(snapshot.get("camera_id", ""))
    camera.manufacturer = str(snapshot.get("manufacturer", ""))
    camera.model = str(snapshot.get("model", ""))
    camera.firmware = str(snapshot.get("firmware", ""))


def _record(camera, actor, action, *, result="accepted", payload=None, message=""):
    item = NetworkCameraAction.objects.create(
        organization=camera.organization,
        camera=camera,
        action=action,
        payload=payload or {},
        result=result,
        message=message,
        requested_by=actor,
    )
    camera.organization.audit_events.create(
        actor=actor,
        action=f"camera.{action}",
        object_type="network-camera",
        object_id=str(camera.id),
        metadata={"result": result, "action_id": str(item.id)},
    )
    return item


@transaction.atomic
def camera_action(*, camera: NetworkCamera, actor, action: str, payload: dict | None = None):
    camera = NetworkCamera.objects.select_for_update().get(pk=camera.pk)
    require_camera_operator(actor, camera.organization)
    payload = payload or {}
    if action == "probe":
        camera.last_probe_at = timezone.now()
        if not camera.capability_snapshot:
            camera.state = NetworkCamera.State.DEGRADED
            camera.last_error = "Ingen valideret capability-snapshot; kør ONVIF-proben."
            camera.save(update_fields=["last_probe_at", "state", "last_error", "updated_at"])
            return _record(camera, actor, action, result="failed", message=camera.last_error)
        camera.state = NetworkCamera.State.ONLINE
        camera.last_error = ""
    elif action == "disable":
        camera.enabled = False
        camera.state = NetworkCamera.State.DISABLED
        camera.tracking_mode = NetworkCamera.TrackingMode.OFF
        camera.ptz_owner = "none"
        camera.ptz_generation += 1
        camera.calibration_valid = False
    elif action == "enable":
        camera.enabled = True
        camera.state = NetworkCamera.State.CONFIGURED
    elif action == "stop":
        camera.tracking_mode = NetworkCamera.TrackingMode.OFF
        camera.ptz_owner = "none"
        camera.ptz_generation += 1
    elif action == "preset":
        preset = str(payload.get("preset_id", camera.preset_id)).strip()
        if not camera.enabled or not preset:
            raise CameraOperationError("an enabled camera and preset are required")
        if camera.ptz_owner not in {"none", "operator"}:
            raise CameraOperationError("preset conflicts with active tracking owner")
        camera.preset_id = preset
        camera.ptz_generation += 1
        camera.calibration_valid = bool(camera.calibration_digest)
    elif action == "tracking":
        mode = str(payload.get("mode", ""))
        if mode not in NetworkCamera.TrackingMode.values:
            raise CameraOperationError("invalid tracking mode")
        if not camera.enabled:
            raise CameraOperationError("camera is disabled")
        capabilities = camera.capability_snapshot
        if mode == NetworkCamera.TrackingMode.NATIVE and not capabilities.get("native_tracking"):
            raise CameraOperationError("native tracking was not discovered")
        if mode == NetworkCamera.TrackingMode.WAGVID and not capabilities.get("ptz", {}).get("continuous"):
            raise CameraOperationError("assisted tracking requires continuous PTZ")
        camera.tracking_mode = mode
        camera.ptz_owner = {
            NetworkCamera.TrackingMode.OFF: "none",
            NetworkCamera.TrackingMode.MANUAL: "operator",
            NetworkCamera.TrackingMode.NATIVE: "camera-native",
            NetworkCamera.TrackingMode.WAGVID: "wagvid",
        }[mode]
        camera.ptz_generation += 1
        if mode != NetworkCamera.TrackingMode.OFF:
            camera.calibration_valid = False
    else:
        raise CameraOperationError("unsupported camera action")
    camera.save()
    return _record(camera, actor, action, payload=payload)
