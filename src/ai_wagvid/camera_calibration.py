"""Immutable camera registry and calibration lifecycle contracts.

Calibration is evidence, not mutable settings. New calibration results supersede older
records by ID while preserving the prior record and its provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class CameraIdentity:
    camera_id: str
    device_id: str
    hardware_fingerprint: str
    display_name: str
    manufacturer: str | None = None
    model: str | None = None
    serial_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.camera_id or not self.device_id or not self.hardware_fingerprint:
            raise CalibrationError("camera_id, device_id and hardware_fingerprint are required")
        if any(character.isspace() for character in self.camera_id):
            raise CalibrationError("camera_id must be a stable whitespace-free identifier")
        if not self.display_name.strip():
            raise CalibrationError("display_name is required")


@dataclass(frozen=True)
class IntrinsicCalibration:
    calibration_id: str
    camera_id: str
    effective_from: datetime
    image_width: int
    image_height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, ...]
    method: str
    sample_count: int
    reprojection_rmse_px: float
    provenance_sha256: str
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.calibration_id, self.camera_id, self.effective_from, self.provenance_sha256)
        if self.image_width < 1 or self.image_height < 1:
            raise CalibrationError("calibration image dimensions must be positive")
        if not math.isfinite(self.fx) or not math.isfinite(self.fy) or self.fx <= 0 or self.fy <= 0:
            raise CalibrationError("focal lengths must be positive finite values")
        for name, value in (("cx", self.cx), ("cy", self.cy)):
            if not math.isfinite(value):
                raise CalibrationError(f"{name} must be finite")
        if not (0 <= self.cx <= self.image_width and 0 <= self.cy <= self.image_height):
            raise CalibrationError("principal point must lie within the calibrated image bounds")
        if any(not math.isfinite(value) for value in self.distortion):
            raise CalibrationError("distortion coefficients must be finite")
        if self.sample_count < 3:
            raise CalibrationError("intrinsic calibration requires at least three samples")
        if not math.isfinite(self.reprojection_rmse_px) or self.reprojection_rmse_px < 0:
            raise CalibrationError("reprojection RMSE must be finite and non-negative")
        if not self.method:
            raise CalibrationError("calibration method is required")

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class ExtrinsicCalibration:
    calibration_id: str
    camera_id: str
    effective_from: datetime
    reference_frame: str
    rotation_row_major: tuple[float, ...]
    translation_m: tuple[float, float, float]
    alignment_rmse_m: float
    sample_count: int
    provenance_sha256: str
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.calibration_id, self.camera_id, self.effective_from, self.provenance_sha256)
        if not self.reference_frame:
            raise CalibrationError("extrinsic reference frame is required")
        if len(self.rotation_row_major) != 9:
            raise CalibrationError("rotation matrix must contain nine values")
        if any(not math.isfinite(value) for value in self.rotation_row_major + self.translation_m):
            raise CalibrationError("extrinsic transform values must be finite")
        _validate_rotation(self.rotation_row_major)
        if not math.isfinite(self.alignment_rmse_m) or self.alignment_rmse_m < 0:
            raise CalibrationError("alignment RMSE must be finite and non-negative")
        if self.sample_count < 3:
            raise CalibrationError("extrinsic calibration requires at least three samples")

    @property
    def digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class CalibrationSelection:
    camera: CameraIdentity
    intrinsic: IntrinsicCalibration | None
    extrinsic: ExtrinsicCalibration | None
    selected_at: datetime
    warnings: tuple[str, ...] = ()

    @property
    def analysis_ready(self) -> bool:
        return self.intrinsic is not None


class CalibrationRegistry:
    def __init__(self, cameras: Iterable[CameraIdentity] = ()) -> None:
        self._cameras: dict[str, CameraIdentity] = {}
        self._intrinsics: dict[str, IntrinsicCalibration] = {}
        self._extrinsics: dict[str, ExtrinsicCalibration] = {}
        for camera in cameras:
            self.add_camera(camera)

    def add_camera(self, camera: CameraIdentity) -> None:
        existing = self._cameras.get(camera.camera_id)
        if existing is not None and existing != camera:
            raise CalibrationError("camera_id is immutable and already describes different hardware")
        if any(
            item.hardware_fingerprint == camera.hardware_fingerprint and item.camera_id != camera.camera_id
            for item in self._cameras.values()
        ):
            raise CalibrationError("hardware fingerprint is already registered to another camera_id")
        self._cameras[camera.camera_id] = camera

    def add_intrinsic(self, calibration: IntrinsicCalibration) -> None:
        self._require_camera(calibration.camera_id)
        self._add_calibration(calibration, self._intrinsics)

    def add_extrinsic(self, calibration: ExtrinsicCalibration) -> None:
        self._require_camera(calibration.camera_id)
        self._add_calibration(calibration, self._extrinsics)

    def select(self, camera_id: str, at: datetime) -> CalibrationSelection:
        camera = self._require_camera(camera_id)
        if at.tzinfo is None or at.utcoffset() is None:
            raise CalibrationError("selection timestamp must be timezone-aware")
        intrinsic = self._select_at(self._intrinsics.values(), camera_id, at)
        extrinsic = self._select_at(self._extrinsics.values(), camera_id, at)
        warnings: list[str] = []
        if intrinsic is None:
            warnings.append("intrinsic-calibration-unavailable")
        if extrinsic is None:
            warnings.append("extrinsic-calibration-unavailable")
        return CalibrationSelection(camera, intrinsic, extrinsic, at, tuple(warnings))

    def intrinsic_history(self, camera_id: str) -> tuple[IntrinsicCalibration, ...]:
        self._require_camera(camera_id)
        return tuple(sorted(
            (item for item in self._intrinsics.values() if item.camera_id == camera_id),
            key=lambda item: (item.effective_from, item.calibration_id),
        ))

    def extrinsic_history(self, camera_id: str) -> tuple[ExtrinsicCalibration, ...]:
        self._require_camera(camera_id)
        return tuple(sorted(
            (item for item in self._extrinsics.values() if item.camera_id == camera_id),
            key=lambda item: (item.effective_from, item.calibration_id),
        ))

    def _require_camera(self, camera_id: str) -> CameraIdentity:
        try:
            return self._cameras[camera_id]
        except KeyError as error:
            raise CalibrationError(f"unknown camera_id: {camera_id}") from error

    @staticmethod
    def _select_at(values, camera_id: str, at: datetime):
        candidates = [
            item for item in values if item.camera_id == camera_id and item.effective_from <= at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.effective_from, item.calibration_id))

    @staticmethod
    def _add_calibration(calibration, store: dict) -> None:
        if calibration.calibration_id in store:
            if store[calibration.calibration_id] == calibration:
                return
            raise CalibrationError("calibration_id is immutable")
        same_camera = [item for item in store.values() if item.camera_id == calibration.camera_id]
        if calibration.supersedes_id is None:
            if same_camera:
                raise CalibrationError("a later calibration must explicitly supersede an earlier record")
        else:
            previous = store.get(calibration.supersedes_id)
            if previous is None:
                raise CalibrationError("supersedes_id does not exist")
            if previous.camera_id != calibration.camera_id:
                raise CalibrationError("calibration cannot supersede another camera")
            if calibration.effective_from <= previous.effective_from:
                raise CalibrationError("superseding calibration must become effective later")
            already_superseded = any(
                item.supersedes_id == previous.calibration_id for item in same_camera
            )
            if already_superseded:
                raise CalibrationError("calibration history cannot fork from one superseded record")
        store[calibration.calibration_id] = calibration


def _validate_identity(
    calibration_id: str,
    camera_id: str,
    effective_from: datetime,
    provenance_sha256: str,
) -> None:
    if not calibration_id or not camera_id:
        raise CalibrationError("calibration_id and camera_id are required")
    if effective_from.tzinfo is None or effective_from.utcoffset() is None:
        raise CalibrationError("effective_from must be timezone-aware")
    if len(provenance_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in provenance_sha256
    ):
        raise CalibrationError("provenance_sha256 must be lowercase hexadecimal")


def _digest(value: dict) -> str:
    normalized = dict(value)
    for key, item in tuple(normalized.items()):
        if isinstance(item, datetime):
            normalized[key] = item.astimezone(UTC).isoformat()
        elif isinstance(item, tuple):
            normalized[key] = list(item)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_rotation(values: tuple[float, ...], *, tolerance: float = 1e-4) -> None:
    rows = [values[0:3], values[3:6], values[6:9]]
    for index, row in enumerate(rows):
        norm = math.sqrt(sum(value * value for value in row))
        if abs(norm - 1.0) > tolerance:
            raise CalibrationError(f"rotation row {index} is not unit length")
    for left in range(3):
        for right in range(left + 1, 3):
            dot = sum(rows[left][i] * rows[right][i] for i in range(3))
            if abs(dot) > tolerance:
                raise CalibrationError("rotation matrix rows are not orthogonal")
    determinant = (
        values[0] * (values[4] * values[8] - values[5] * values[7])
        - values[1] * (values[3] * values[8] - values[5] * values[6])
        + values[2] * (values[3] * values[7] - values[4] * values[6])
    )
    if abs(determinant - 1.0) > tolerance:
        raise CalibrationError("rotation matrix determinant must be +1")
