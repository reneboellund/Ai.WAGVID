"""Versioned 2D apparatus calibration and multi-camera clock mapping."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .domain import Apparatus, TimeRange

Point = tuple[float, float]


@dataclass(frozen=True)
class ApparatusCalibration:
    calibration_id: str
    camera_id: str
    apparatus: Apparatus
    source_sha256: str
    revision: int
    valid_interval: TimeRange
    geometry: dict[str, Any]
    created_at: datetime
    author_id: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.calibration_id or not self.camera_id or not self.author_id or self.revision < 1:
            raise ValueError("calibration identity, author and positive revision are required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("calibration timestamp must be timezone-aware")
        if len(self.source_sha256) != 64:
            raise ValueError("calibration requires source SHA-256")
        _validate_geometry(self.apparatus, self.geometry)

    @property
    def digest(self) -> str:
        value = asdict(self)
        value["apparatus"] = self.apparatus.value
        value["created_at"] = self.created_at.astimezone(UTC).isoformat()
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _point(value: Any, name: str) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be a 2D point")
    point = (float(value[0]), float(value[1]))
    if not all(0 <= coordinate <= 1 for coordinate in point):
        raise ValueError(f"{name} must use normalized image coordinates")
    return point


def _validate_geometry(apparatus: Apparatus, value: dict[str, Any]) -> None:
    required: dict[Apparatus, tuple[str, ...]] = {
        Apparatus.VT: ("table_center", "board_center", "landing_line"),
        Apparatus.UB: ("low_bar_center", "high_bar_center"),
        Apparatus.BB: ("beam_start", "beam_end"),
        Apparatus.FX: ("floor_polygon",),
    }
    if apparatus not in required:
        if not value:
            raise ValueError("MAG calibration requires explicit geometry")
        return
    missing = set(required[apparatus]) - set(value)
    if missing:
        raise ValueError(f"calibration lacks geometry: {', '.join(sorted(missing))}")
    if apparatus is Apparatus.FX:
        polygon = value["floor_polygon"]
        if not isinstance(polygon, list) or len(polygon) < 3:
            raise ValueError("floor polygon requires at least three points")
        for index, item in enumerate(polygon):
            _point(item, f"floor_polygon[{index}]")
    else:
        for name in required[apparatus]:
            if name == "landing_line":
                line = value[name]
                if not isinstance(line, list) or len(line) != 2:
                    raise ValueError("landing_line requires two points")
                _point(line[0], "landing_line[0]")
                _point(line[1], "landing_line[1]")
            else:
                _point(value[name], name)


@dataclass(frozen=True)
class CameraClockMapping:
    camera_id: str
    reference_camera_id: str
    offset_s: float
    drift_ppm: float
    measured_at_s: tuple[float, ...]
    residual_error_ms: float
    config_digest: str
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.camera_id == self.reference_camera_id or not self.measured_at_s:
            raise ValueError("clock mapping requires distinct cameras and measurements")
        if self.residual_error_ms < 0 or len(self.config_digest) != 64:
            raise ValueError("clock mapping error/digest is invalid")

    def to_reference_time(self, camera_timestamp_s: float) -> float:
        if camera_timestamp_s < 0:
            raise ValueError("camera timestamp cannot be negative")
        return camera_timestamp_s + self.offset_s + camera_timestamp_s * self.drift_ppm / 1_000_000

    def uncertainty_ms(self, camera_timestamp_s: float) -> float:
        nearest = min(abs(camera_timestamp_s - measured) for measured in self.measured_at_s)
        drift_uncertainty = nearest * abs(self.drift_ppm) / 1000
        return self.residual_error_ms + drift_uncertainty
