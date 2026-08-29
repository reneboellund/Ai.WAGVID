from datetime import UTC, datetime

import pytest

from ai_wagvid.camera_sources import (
    CameraEventKind,
    CameraProfile,
    CameraSourceError,
    PresetCalibrationBinding,
    PTZOwner,
    PTZSample,
    TrackingMode,
    camera_capabilities_payload,
    ptz_timeline_payload,
)
from ai_wagvid.dahua_camera import DahuaCameraAdapter, TrackingPolicy


class OnvifFixture:
    def __init__(self):
        self.moves = []
        self.stops = 0

    def device_information(self):
        return {"manufacturer": "Dahua Technology", "model": "PTZ-fixture", "firmware": "1.2.3", "https_supported": True}

    def profiles(self):
        return {"T", "G", "M"}

    def streams(self):
        return [
            {"id": "main", "uri": "rtsp://camera/main", "codec": "H265", "width": 3840, "height": 2160, "fps": 50, "bitrate_kbps": 16000},
            {"id": "preview", "uri": "rtsp://camera/sub", "codec": "H264", "width": 1280, "height": 720, "fps": 25, "canonical_eligible": False},
        ]

    def ptz_capabilities(self):
        return {"continuous": True, "relative": True, "absolute": True, "presets": True, "optical_zoom": True}

    def stop_ptz(self):
        self.stops += 1

    def goto_preset(self, preset_id):
        self.moves.append(("preset", preset_id))

    def continuous_move(self, pan, tilt, zoom):
        self.moves.append((pan, tilt, zoom))


class ExtensionFixture:
    def __init__(self):
        self.tracking = []

    def capabilities(self):
        return {"native_tracking": True, "event_kinds": ["motion", "human", "tripwire"]}

    def set_native_tracking(self, enabled):
        self.tracking.append(enabled)


def fixture():
    onvif = OnvifFixture()
    extension = ExtensionFixture()
    return DahuaCameraAdapter("cam-1", onvif, extension), onvif, extension


def test_capability_discovery_is_dynamic_and_separates_main_from_preview():
    adapter, _onvif, _extension = fixture()
    capabilities = adapter.discover()
    assert capabilities.profiles == frozenset({CameraProfile.T, CameraProfile.G, CameraProfile.M})
    assert capabilities.edge_recording and capabilities.native_tracking
    assert capabilities.streams[0].canonical_eligible
    assert not capabilities.streams[1].canonical_eligible
    assert len(capabilities.digest) == 64
    assert camera_capabilities_payload(capabilities)["capability_digest"] == capabilities.digest


def test_non_dahua_identity_fails_closed():
    adapter, onvif, _extension = fixture()
    onvif.device_information = lambda: {"manufacturer": "Other", "model": "x"}
    with pytest.raises(CameraSourceError, match="Dahua"):
        adapter.discover()


def test_native_and_wagvid_tracking_cannot_own_ptz_together():
    adapter, _onvif, extension = fixture()
    capabilities = adapter.discover()
    adapter.set_tracking(TrackingMode.NATIVE, capabilities)
    assert adapter.ownership.owner is PTZOwner.CAMERA_NATIVE
    assert extension.tracking == [True]
    with pytest.raises(CameraSourceError, match="already owned"):
        adapter.set_tracking(TrackingMode.WAGVID_ASSISTED, capabilities)


def test_manual_emergency_stop_always_wins():
    adapter, onvif, extension = fixture()
    adapter.set_tracking(TrackingMode.NATIVE, adapter.discover())
    adapter.emergency_stop()
    assert adapter.ownership.owner is PTZOwner.NONE
    assert onvif.stops == 1
    assert extension.tracking[-1] is False


def test_assisted_tracking_holds_on_low_confidence_and_enforces_bounds():
    adapter, onvif, _extension = fixture()
    capabilities = adapter.discover()
    adapter.set_tracking(TrackingMode.WAGVID_ASSISTED, capabilities)
    policy = TrackingPolicy(mode=TrackingMode.WAGVID_ASSISTED, max_zoom_milli=500)
    assert not adapter.assisted_move(pan=0.1, tilt=0.1, zoom=0.2, confidence_milli=500, policy=policy)
    assert onvif.stops == 1
    assert adapter.assisted_move(pan=0.1, tilt=-0.2, zoom=0.3, confidence_milli=900, policy=policy)
    with pytest.raises(CameraSourceError, match="bounds"):
        adapter.assisted_move(pan=0.1, tilt=0.1, zoom=0.8, confidence_milli=900, policy=policy)


def test_camera_events_are_acquisition_evidence_not_identity_or_scores():
    adapter, _onvif, _extension = fixture()
    event = adapter.normalize_event({"id": "e1", "topic": "SmartMotionHuman", "occurred_at": datetime.now(UTC), "active": True})
    assert event.kind is CameraEventKind.HUMAN
    assert not hasattr(event, "athlete_id")
    assert not hasattr(event, "score")


def test_preset_calibration_invalidates_on_motion_or_wrong_zoom():
    binding = PresetCalibrationBinding("cam-1", "vault", "a" * 64, 0, 0, 500, 10)
    sample = PTZSample(datetime.now(UTC), 2, -2, 505, "vault", TrackingMode.OFF, PTZOwner.NONE, False, "onvif")
    assert binding.valid_for(sample)
    assert not binding.valid_for(PTZSample(**{**sample.__dict__, "moving": True}))
    assert not binding.valid_for(PTZSample(**{**sample.__dict__, "optical_zoom_milli": 700}))


def test_ptz_timeline_is_digest_bound():
    sample = PTZSample(datetime.now(UTC), 0, 0, 100, "beam", TrackingMode.OFF, PTZOwner.NONE, False, "onvif")
    payload = ptz_timeline_payload("cam-1", (sample,))
    assert payload["schema"] == "ai.wagvid.camera-ptz-timeline.v1"
    assert len(payload["timeline_digest"]) == 64
