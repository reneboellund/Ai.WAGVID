import json

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.camera_operations import CameraOperationError, camera_action
from wagvid_app.models import Membership, NetworkCamera, Organization


def capability(*, native=True, continuous=True):
    return {
        "schema": "ai.wagvid.camera-capabilities.v1",
        "camera_id": "dahua-lab-1",
        "manufacturer": "Dahua Technology",
        "model": "PTZ fixture",
        "firmware": "1.2.3",
        "profiles": ["T", "G", "M"],
        "streams": [
            {
                "profile_id": "main", "name": "Main", "uri": "rtsp://camera/main",
                "codec": "H265", "width": 3840, "height": 2160, "fps_milli": 50000,
                "bitrate_kbps": 16000, "canonical_eligible": True,
            },
            {
                "profile_id": "preview", "name": "Preview", "uri": "rtsp://camera/sub",
                "codec": "H264", "width": 1280, "height": 720, "fps_milli": 25000,
                "bitrate_kbps": 3000, "canonical_eligible": False,
            },
        ],
        "ptz": {"continuous": continuous, "presets": True, "absolute": True},
        "events": ["motion", "human"],
        "native_tracking": native,
        "edge_recording": True,
        "https_supported": True,
        "capability_digest": "a" * 64,
    }


def setup_camera(role=Membership.Role.ORGANIZATION_ADMIN):
    organization = Organization.objects.create(name="Camera Club", slug=f"camera-{role}")
    user = User.objects.create_user(f"camera-{role}", password="secret")
    Membership.objects.create(user=user, organization=organization, role=role)
    camera = NetworkCamera.objects.create(
        organization=organization,
        name="Floor PTZ",
        provider=NetworkCamera.Provider.DAHUA,
        endpoint="https://10.0.0.20",
        username_secret_ref="vault:camera/user",
        password_secret_ref="vault:camera/password",
        capability_snapshot=capability(),
        stable_device_id="dahua-lab-1",
        canonical_profile_id="main",
        preview_profile_id="preview",
        calibration_digest="b" * 64,
        preset_id="floor",
    )
    return organization, user, camera


@pytest.mark.django_db
def test_camera_control_enforces_single_owner_emergency_stop_and_calibration():
    organization, user, camera = setup_camera()
    camera_action(camera=camera, actor=user, action="preset", payload={"preset_id": "floor"})
    camera.refresh_from_db()
    assert camera.calibration_valid is True
    camera_action(camera=camera, actor=user, action="tracking", payload={"mode": "native"})
    camera.refresh_from_db()
    assert camera.ptz_owner == "camera-native"
    assert camera.calibration_valid is False
    with pytest.raises(CameraOperationError, match="conflicts"):
        camera_action(camera=camera, actor=user, action="preset", payload={"preset_id": "beam"})
    camera_action(camera=camera, actor=user, action="stop")
    camera.refresh_from_db()
    assert camera.ptz_owner == "none"
    assert camera.tracking_mode == "off"
    assert organization.audit_events.filter(action="camera.stop").exists()


@pytest.mark.django_db
def test_camera_actions_are_role_and_capability_gated():
    _, viewer, camera = setup_camera(Membership.Role.VIEWER)
    with pytest.raises(PermissionError, match="operator role"):
        camera_action(camera=camera, actor=viewer, action="stop")
    Membership.objects.filter(user=viewer).update(role=Membership.Role.OPERATOR)
    camera.capability_snapshot = capability(native=False)
    camera.save()
    with pytest.raises(CameraOperationError, match="not discovered"):
        camera_action(camera=camera, actor=viewer, action="tracking", payload={"mode": "native"})


@pytest.mark.django_db
def test_camera_setup_and_controls_are_available_in_gui(client):
    organization = Organization.objects.create(name="UI Camera Club", slug="ui-camera-club")
    user = User.objects.create_user("ui-camera-admin", password="secret")
    Membership.objects.create(
        user=user, organization=organization, role=Membership.Role.ORGANIZATION_ADMIN
    )
    client.force_login(user)
    response = client.post(
        reverse("camera-create"),
        {
            "name": "Vault camera", "provider": "dahua", "endpoint": "https://10.0.0.21",
            "username_secret_ref": "env:CAMERA_USER", "password_secret_ref": "env:CAMERA_PASSWORD",
            "tls_verify": "on", "apparatus": "VT", "canonical_profile_id": "main",
            "preview_profile_id": "preview", "preset_id": "vault",
            "calibration_digest": "c" * 64, "capability_json": json.dumps(capability()),
        },
    )
    camera = organization.network_cameras.get()
    assert response.status_code == 302
    assert response.url == reverse("camera-detail", args=[camera.id])
    detail = client.get(response.url).content.decode()
    assert "PTZ NØDSTOP" in detail
    assert "Anvend tracking" in detail
    assert "Main" in detail and "Preview" in detail
    stop = client.post(reverse("camera-control", args=[camera.id]), {"action": "stop"})
    assert stop.status_code == 302
    assert camera.actions.filter(action="stop", result="accepted").exists()


@pytest.mark.django_db
def test_camera_gui_rejects_plaintext_credentials_and_cross_org_access(client):
    own, _, camera = setup_camera()
    other = Organization.objects.create(name="Other Camera Club", slug="other-camera-club")
    outsider = User.objects.create_user("camera-outsider", password="secret")
    Membership.objects.create(
        user=outsider, organization=other, role=Membership.Role.ORGANIZATION_ADMIN
    )
    client.force_login(outsider)
    assert client.get(reverse("camera-detail", args=[camera.id])).status_code == 404
    response = client.post(
        reverse("camera-create"),
        {
            "name": "Unsafe", "provider": "dahua", "endpoint": "https://10.0.0.2",
            "username_secret_ref": "admin", "password_secret_ref": "password",
            "tls_verify": "on", "apparatus": "", "canonical_profile_id": "",
            "preview_profile_id": "", "preset_id": "", "calibration_digest": "",
        },
    )
    assert response.status_code == 200
    assert "secret-reference" in response.content.decode()
    assert own.network_cameras.count() == 1
