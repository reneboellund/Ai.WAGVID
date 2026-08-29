"""Dahua adapter composed from portable ONVIF and optional documented vendor gateways."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .camera_sources import (
    CameraCapabilities,
    CameraEvent,
    CameraEventKind,
    CameraProfile,
    CameraSourceError,
    CameraStreamProfile,
    PTZCapabilities,
    PTZOwner,
    PTZOwnership,
    TrackingMode,
)


class OnvifGateway(Protocol):
    def device_information(self) -> dict: ...
    def profiles(self) -> set[str]: ...
    def streams(self) -> list[dict]: ...
    def ptz_capabilities(self) -> dict: ...
    def stop_ptz(self) -> None: ...
    def goto_preset(self, preset_id: str) -> None: ...
    def continuous_move(self, pan: float, tilt: float, zoom: float) -> None: ...


class DahuaExtensionGateway(Protocol):
    def capabilities(self) -> dict: ...
    def set_native_tracking(self, enabled: bool) -> None: ...


@dataclass(frozen=True)
class TrackingPolicy:
    mode: TrackingMode
    allowed_pan_min_milli: int = -1000
    allowed_pan_max_milli: int = 1000
    allowed_tilt_min_milli: int = -1000
    allowed_tilt_max_milli: int = 1000
    max_zoom_milli: int = 1000
    minimum_confidence_milli: int = 750


class DahuaCameraAdapter:
    def __init__(
        self,
        camera_id: str,
        onvif: OnvifGateway,
        extension: DahuaExtensionGateway | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.onvif = onvif
        self.extension = extension
        self.ownership = PTZOwnership()
        self.tracking_mode = TrackingMode.OFF

    def discover(self) -> CameraCapabilities:
        info = self.onvif.device_information()
        manufacturer = str(info.get("manufacturer", ""))
        if "dahua" not in manufacturer.casefold():
            raise CameraSourceError("device does not identify as Dahua")
        profiles = frozenset(
            CameraProfile(value) for value in self.onvif.profiles() if value in CameraProfile
        )
        streams = tuple(
            CameraStreamProfile(
                profile_id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                uri=str(item["uri"]),
                codec=str(item["codec"]),
                width=int(item["width"]),
                height=int(item["height"]),
                fps_milli=round(float(item["fps"]) * 1000),
                bitrate_kbps=int(item["bitrate_kbps"]) if item.get("bitrate_kbps") else None,
                canonical_eligible=bool(item.get("canonical_eligible", True)),
            )
            for item in self.onvif.streams()
        )
        ptz_raw = self.onvif.ptz_capabilities()
        vendor = self.extension.capabilities() if self.extension else {}
        events = {
            CameraEventKind(value)
            for value in vendor.get("event_kinds", [])
            if value in CameraEventKind
        }
        return CameraCapabilities(
            camera_id=self.camera_id,
            manufacturer=manufacturer,
            model=str(info.get("model", "unknown")),
            firmware=str(info.get("firmware", "unknown")),
            profiles=profiles,
            streams=streams,
            ptz=PTZCapabilities(**{key: bool(ptz_raw.get(key, False)) for key in PTZCapabilities.__dataclass_fields__}),
            event_kinds=frozenset(events),
            native_tracking=bool(vendor.get("native_tracking", False)),
            edge_recording=CameraProfile.G in profiles,
            https_supported=bool(info.get("https_supported", False)),
        )

    def set_tracking(self, mode: TrackingMode, capabilities: CameraCapabilities) -> None:
        if mode is TrackingMode.NATIVE:
            if not capabilities.native_tracking or not self.extension:
                raise CameraSourceError("native tracking was not discovered")
            generation = self.ownership.acquire(PTZOwner.CAMERA_NATIVE)
            try:
                self.extension.set_native_tracking(True)
            except Exception:
                self.ownership.release(PTZOwner.CAMERA_NATIVE, generation)
                raise
        elif mode is TrackingMode.WAGVID_ASSISTED:
            if not capabilities.ptz.continuous:
                raise CameraSourceError("assisted tracking requires continuous PTZ")
            if self.extension and self.tracking_mode is TrackingMode.NATIVE:
                self.extension.set_native_tracking(False)
            self.ownership.acquire(PTZOwner.WAGVID)
        elif mode in {TrackingMode.OFF, TrackingMode.MANUAL}:
            self.emergency_stop()
            if mode is TrackingMode.MANUAL:
                self.ownership.acquire(PTZOwner.OPERATOR)
        self.tracking_mode = mode

    def assisted_move(self, *, pan: float, tilt: float, zoom: float, confidence_milli: int, policy: TrackingPolicy) -> bool:
        if self.ownership.owner is not PTZOwner.WAGVID or policy.mode is not TrackingMode.WAGVID_ASSISTED:
            raise CameraSourceError("WAGVID does not own PTZ")
        if confidence_milli < policy.minimum_confidence_milli:
            self.onvif.stop_ptz()
            return False
        values = (int(pan * 1000), int(tilt * 1000), int(zoom * 1000))
        if not (
            policy.allowed_pan_min_milli <= values[0] <= policy.allowed_pan_max_milli
            and policy.allowed_tilt_min_milli <= values[1] <= policy.allowed_tilt_max_milli
            and 0 <= values[2] <= policy.max_zoom_milli
        ):
            raise CameraSourceError("PTZ target exceeds configured safety bounds")
        self.onvif.continuous_move(pan, tilt, zoom)
        return True

    def goto_preset(self, preset_id: str, capabilities: CameraCapabilities) -> None:
        if not capabilities.ptz.presets:
            raise CameraSourceError("camera does not expose presets")
        if self.ownership.owner not in {PTZOwner.NONE, PTZOwner.OPERATOR}:
            raise CameraSourceError("preset move conflicts with active tracking owner")
        self.onvif.goto_preset(preset_id)

    def emergency_stop(self) -> None:
        self.onvif.stop_ptz()
        if self.extension and self.tracking_mode is TrackingMode.NATIVE:
            self.extension.set_native_tracking(False)
        self.ownership.emergency_stop()
        self.tracking_mode = TrackingMode.OFF

    def normalize_event(self, raw: dict) -> CameraEvent:
        topic = str(raw.get("topic", ""))
        mapping = {
            "VideoMotion": CameraEventKind.MOTION,
            "SmartMotionHuman": CameraEventKind.HUMAN,
            "CrossLineDetection": CameraEventKind.TRIPWIRE,
            "CrossRegionDetection": CameraEventKind.REGION_ENTRY,
            "VideoBlind": CameraEventKind.TAMPER,
        }
        return CameraEvent(
            event_id=str(raw["id"]),
            camera_id=self.camera_id,
            kind=mapping.get(topic, CameraEventKind.UNKNOWN),
            occurred_at=raw["occurred_at"],
            active=bool(raw.get("active", True)),
            source=str(raw.get("source", "dahua-cgi")),
            confidence_milli=raw.get("confidence_milli"),
            vendor_topic=topic or None,
        )
