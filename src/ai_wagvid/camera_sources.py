"""Provider-neutral network camera, PTZ ownership and provenance contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum


class CameraSourceError(ValueError):
    pass


class CameraProfile(StrEnum):
    T = "T"
    G = "G"
    M = "M"
    S = "S"


class TrackingMode(StrEnum):
    OFF = "off"
    MANUAL = "manual"
    NATIVE = "native"
    WAGVID_ASSISTED = "wagvid-assisted"


class PTZOwner(StrEnum):
    NONE = "none"
    OPERATOR = "operator"
    CAMERA_NATIVE = "camera-native"
    WAGVID = "wagvid"


class CameraEventKind(StrEnum):
    MOTION = "motion"
    HUMAN = "human"
    REGION_ENTRY = "region-entry"
    TRIPWIRE = "tripwire"
    TRACKING_STARTED = "tracking-started"
    TRACKING_STOPPED = "tracking-stopped"
    TRACKING_LOST = "tracking-lost"
    TAMPER = "tamper"
    STORAGE = "storage"
    HEALTH = "health"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CameraStreamProfile:
    profile_id: str
    name: str
    uri: str
    codec: str
    width: int
    height: int
    fps_milli: int
    bitrate_kbps: int | None = None
    canonical_eligible: bool = True

    def __post_init__(self) -> None:
        if not self.profile_id or not self.uri.startswith(("rtsp://", "rtsps://")):
            raise CameraSourceError("camera stream identity/URI is invalid")
        if min(self.width, self.height, self.fps_milli) <= 0:
            raise CameraSourceError("camera stream dimensions/FPS must be positive")


@dataclass(frozen=True)
class PTZCapabilities:
    continuous: bool = False
    relative: bool = False
    absolute: bool = False
    presets: bool = False
    home: bool = False
    optical_zoom: bool = False
    focus: bool = False
    tours: bool = False


@dataclass(frozen=True)
class CameraCapabilities:
    camera_id: str
    manufacturer: str
    model: str
    firmware: str
    profiles: frozenset[CameraProfile]
    streams: tuple[CameraStreamProfile, ...]
    ptz: PTZCapabilities
    event_kinds: frozenset[CameraEventKind] = frozenset()
    native_tracking: bool = False
    edge_recording: bool = False
    https_supported: bool = False
    probed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.camera_id or not self.manufacturer or not self.model or not self.streams:
            raise CameraSourceError("camera capability snapshot is incomplete")
        if len({item.profile_id for item in self.streams}) != len(self.streams):
            raise CameraSourceError("camera stream profile identifiers must be unique")
        if self.edge_recording and CameraProfile.G not in self.profiles:
            raise CameraSourceError("edge recording requires discovered ONVIF Profile G")
        if self.probed_at is not None and (
            self.probed_at.tzinfo is None or self.probed_at.utcoffset() is None
        ):
            raise CameraSourceError("camera probe timestamp must be timezone-aware")

    @property
    def digest(self) -> str:
        return _digest(_json_value(asdict(self)))


@dataclass(frozen=True)
class CameraEvent:
    event_id: str
    camera_id: str
    kind: CameraEventKind
    occurred_at: datetime
    active: bool
    source: str
    confidence_milli: int | None = None
    vendor_topic: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.camera_id or not self.source:
            raise CameraSourceError("camera event identity is incomplete")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CameraSourceError("camera event timestamp must be timezone-aware")
        if self.confidence_milli is not None and not 0 <= self.confidence_milli <= 1000:
            raise CameraSourceError("camera event confidence must be [0,1000]")


@dataclass(frozen=True)
class PTZSample:
    occurred_at: datetime
    pan_milli: int | None
    tilt_milli: int | None
    optical_zoom_milli: int | None
    preset_id: str | None
    tracking_mode: TrackingMode
    owner: PTZOwner
    moving: bool
    source: str

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CameraSourceError("PTZ sample timestamp must be timezone-aware")
        if not self.source:
            raise CameraSourceError("PTZ sample source is required")


@dataclass(frozen=True)
class PresetCalibrationBinding:
    camera_id: str
    preset_id: str
    calibration_digest: str
    expected_pan_milli: int
    expected_tilt_milli: int
    expected_zoom_milli: int
    tolerance_milli: int

    def __post_init__(self) -> None:
        if len(self.calibration_digest) != 64 or any(
            item not in "0123456789abcdef" for item in self.calibration_digest
        ):
            raise CameraSourceError("calibration digest must be lowercase SHA-256")
        if self.tolerance_milli < 0:
            raise CameraSourceError("calibration tolerance cannot be negative")

    def valid_for(self, sample: PTZSample) -> bool:
        if sample.moving or sample.preset_id != self.preset_id:
            return False
        values = (sample.pan_milli, sample.tilt_milli, sample.optical_zoom_milli)
        if any(value is None for value in values):
            return False
        expected = (
            self.expected_pan_milli,
            self.expected_tilt_milli,
            self.expected_zoom_milli,
        )
        return all(abs(value - target) <= self.tolerance_milli for value, target in zip(values, expected, strict=True))


class PTZOwnership:
    """Single-owner PTZ lease with unconditional local emergency stop."""

    def __init__(self) -> None:
        self.owner = PTZOwner.NONE
        self.generation = 0

    def acquire(self, owner: PTZOwner) -> int:
        if owner is PTZOwner.NONE:
            raise CameraSourceError("none cannot acquire PTZ")
        if self.owner not in {PTZOwner.NONE, owner}:
            raise CameraSourceError(f"PTZ is already owned by {self.owner.value}")
        self.owner = owner
        self.generation += 1
        return self.generation

    def release(self, owner: PTZOwner, generation: int) -> None:
        if self.owner is not owner or self.generation != generation:
            raise CameraSourceError("stale or foreign PTZ release")
        self.owner = PTZOwner.NONE

    def emergency_stop(self) -> None:
        self.owner = PTZOwner.NONE
        self.generation += 1


def ptz_timeline_payload(camera_id: str, samples: tuple[PTZSample, ...]) -> dict:
    if not camera_id or not samples:
        raise CameraSourceError("PTZ timeline requires camera and samples")
    ordered = tuple(sorted(samples, key=lambda item: item.occurred_at))
    payload = {
        "schema": "ai.wagvid.camera-ptz-timeline.v1",
        "camera_id": camera_id,
        "created_at": datetime.now(UTC).isoformat(),
        "samples": [_json_value(asdict(item)) for item in ordered],
    }
    payload["timeline_digest"] = _digest(payload)
    return payload


def camera_capabilities_payload(capabilities: CameraCapabilities) -> dict:
    return {
        "schema": "ai.wagvid.camera-capabilities.v1",
        "camera_id": capabilities.camera_id,
        "manufacturer": capabilities.manufacturer,
        "model": capabilities.model,
        "firmware": capabilities.firmware,
        "profiles": sorted(item.value for item in capabilities.profiles),
        "streams": [_json_value(asdict(item)) for item in capabilities.streams],
        "ptz": _json_value(asdict(capabilities.ptz)),
        "events": sorted(item.value for item in capabilities.event_kinds),
        "native_tracking": capabilities.native_tracking,
        "edge_recording": capabilities.edge_recording,
        "https_supported": capabilities.https_supported,
        "capability_digest": capabilities.digest,
    }


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    if isinstance(value, (StrEnum,)):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
