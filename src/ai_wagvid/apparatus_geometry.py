"""Versioned single-camera 2D apparatus geometry contracts.

The geometry layer records only what was actually calibrated in a source image. It does
not infer missing boundaries or claim metric 3D measurements from a 2D image. Coordinates
are normalized to the calibrated image so records remain resolution-independent while
remaining tied to the exact camera/calibration provenance that produced them.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Iterable, Protocol


class ApparatusGeometryError(ValueError):
    pass


class Apparatus(StrEnum):
    VT = "VT"
    UB = "UB"
    BB = "BB"
    FX = "FX"


@dataclass(frozen=True)
class ImagePoint:
    x: float
    y: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ApparatusGeometryError("image point coordinates must be finite")
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ApparatusGeometryError("image point coordinates must be normalized to [0, 1]")

    def distance_to(self, other: "ImagePoint") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True)
class ImageSegment:
    start: ImagePoint
    end: ImagePoint

    def __post_init__(self) -> None:
        if self.start.distance_to(self.end) <= 1e-9:
            raise ApparatusGeometryError("image segment must have non-zero length")

    @property
    def midpoint(self) -> ImagePoint:
        return ImagePoint((self.start.x + self.end.x) / 2.0, (self.start.y + self.end.y) / 2.0)

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)


@dataclass(frozen=True)
class ImagePolygon:
    vertices: tuple[ImagePoint, ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise ApparatusGeometryError("image polygon requires at least three vertices")
        if len(set(self.vertices)) != len(self.vertices):
            raise ApparatusGeometryError("image polygon vertices must be unique")
        if abs(self.signed_area) <= 1e-9:
            raise ApparatusGeometryError("image polygon must enclose a non-zero area")
        if _polygon_self_intersects(self.vertices):
            raise ApparatusGeometryError("image polygon must not self-intersect")

    @property
    def signed_area(self) -> float:
        return 0.5 * sum(
            left.x * right.y - right.x * left.y
            for left, right in zip(self.vertices, self.vertices[1:] + self.vertices[:1])
        )

    @property
    def area(self) -> float:
        return abs(self.signed_area)

    def contains(self, point: ImagePoint, *, boundary_tolerance: float = 1e-9) -> bool:
        if boundary_tolerance < 0:
            raise ApparatusGeometryError("boundary tolerance cannot be negative")
        for left, right in zip(self.vertices, self.vertices[1:] + self.vertices[:1]):
            if _point_segment_distance(point, left, right) <= boundary_tolerance:
                return True
        inside = False
        previous = self.vertices[-1]
        for current in self.vertices:
            crosses = (current.y > point.y) != (previous.y > point.y)
            if crosses:
                x_at_y = (
                    (previous.x - current.x)
                    * (point.y - current.y)
                    / (previous.y - current.y)
                    + current.x
                )
                if point.x < x_at_y:
                    inside = not inside
            previous = current
        return inside


class ApparatusGeometry(Protocol):
    @property
    def apparatus(self) -> Apparatus: ...

    @property
    def capabilities(self) -> frozenset[str]: ...


@dataclass(frozen=True)
class VaultGeometry:
    table_region: ImagePolygon
    springboard_region: ImagePolygon
    landing_centerline: ImageSegment | None = None
    landing_region: ImagePolygon | None = None

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.VT

    @property
    def capabilities(self) -> frozenset[str]:
        values = {"table-region", "springboard-region"}
        if self.landing_centerline is not None:
            values.add("landing-centerline")
        if self.landing_region is not None:
            values.add("landing-region")
        return frozenset(values)


@dataclass(frozen=True)
class UnevenBarsGeometry:
    high_bar_axis: ImageSegment
    low_bar_axis: ImageSegment

    def __post_init__(self) -> None:
        if self.high_bar_axis.midpoint.distance_to(self.low_bar_axis.midpoint) <= 1e-6:
            raise ApparatusGeometryError("high and low bar axes must describe different bars")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.UB

    @property
    def high_bar_center(self) -> ImagePoint:
        return self.high_bar_axis.midpoint

    @property
    def low_bar_center(self) -> ImagePoint:
        return self.low_bar_axis.midpoint

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"high-bar-axis", "low-bar-axis", "bar-centers"})


@dataclass(frozen=True)
class BeamGeometry:
    beam_region: ImagePolygon
    beam_axis: ImageSegment

    def __post_init__(self) -> None:
        if not self.beam_region.contains(self.beam_axis.start, boundary_tolerance=1e-6):
            raise ApparatusGeometryError("beam axis start must lie within the beam region")
        if not self.beam_region.contains(self.beam_axis.end, boundary_tolerance=1e-6):
            raise ApparatusGeometryError("beam axis end must lie within the beam region")

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.BB

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"beam-region", "beam-axis", "beam-ends"})


@dataclass(frozen=True)
class FloorGeometry:
    floor_polygon: ImagePolygon

    @property
    def apparatus(self) -> Apparatus:
        return Apparatus.FX

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"floor-boundary"})


@dataclass(frozen=True)
class ApparatusGeometryRecord:
    geometry_id: str
    camera_id: str
    intrinsic_calibration_id: str
    extrinsic_calibration_id: str | None
    effective_from: datetime
    source_media_sha256: str
    source_frame_index: int
    method: str
    quality_score: float
    geometry: VaultGeometry | UnevenBarsGeometry | BeamGeometry | FloorGeometry
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        if not self.geometry_id or not self.camera_id or not self.intrinsic_calibration_id:
            raise ApparatusGeometryError("geometry_id, camera_id and intrinsic calibration are required")
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ApparatusGeometryError("effective_from must be timezone-aware")
        if len(self.source_media_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_media_sha256
        ):
            raise ApparatusGeometryError("source_media_sha256 must be lowercase hexadecimal")
        if self.source_frame_index < 0:
            raise ApparatusGeometryError("source_frame_index cannot be negative")
        if not self.method.strip():
            raise ApparatusGeometryError("geometry calibration method is required")
        if not math.isfinite(self.quality_score) or not 0.0 <= self.quality_score <= 1.0:
            raise ApparatusGeometryError("quality_score must be in [0, 1]")

    @property
    def apparatus(self) -> Apparatus:
        return self.geometry.apparatus

    @property
    def digest(self) -> str:
        payload = asdict(self)
        payload["effective_from"] = self.effective_from.astimezone(UTC).isoformat()
        payload["apparatus"] = self.apparatus.value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ApparatusGeometryRegistry:
    """Append-only geometry history with one linear supersession chain per camera/apparatus."""

    def __init__(self, records: Iterable[ApparatusGeometryRecord] = ()) -> None:
        self._records: dict[str, ApparatusGeometryRecord] = {}
        for record in records:
            self.add(record)

    def add(self, record: ApparatusGeometryRecord) -> None:
        existing = self._records.get(record.geometry_id)
        if existing is not None:
            if existing == record:
                return
            raise ApparatusGeometryError("geometry_id is immutable")
        chain = [
            item
            for item in self._records.values()
            if item.camera_id == record.camera_id and item.apparatus == record.apparatus
        ]
        if record.supersedes_id is None:
            if chain:
                raise ApparatusGeometryError("later apparatus geometry must supersede the prior record")
        else:
            previous = self._records.get(record.supersedes_id)
            if previous is None:
                raise ApparatusGeometryError("supersedes_id does not exist")
            if previous.camera_id != record.camera_id or previous.apparatus != record.apparatus:
                raise ApparatusGeometryError("geometry can only supersede the same camera/apparatus")
            if record.effective_from <= previous.effective_from:
                raise ApparatusGeometryError("superseding geometry must become effective later")
            if any(item.supersedes_id == previous.geometry_id for item in chain):
                raise ApparatusGeometryError("apparatus geometry history cannot fork")
        self._records[record.geometry_id] = record

    def select(self, camera_id: str, apparatus: Apparatus, at: datetime) -> ApparatusGeometryRecord | None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ApparatusGeometryError("selection timestamp must be timezone-aware")
        candidates = [
            item
            for item in self._records.values()
            if item.camera_id == camera_id
            and item.apparatus == apparatus
            and item.effective_from <= at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.effective_from, item.geometry_id))

    def history(self, camera_id: str, apparatus: Apparatus) -> tuple[ApparatusGeometryRecord, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._records.values()
                    if item.camera_id == camera_id and item.apparatus == apparatus
                ),
                key=lambda item: (item.effective_from, item.geometry_id),
            )
        )


def require_geometry_capabilities(
    record: ApparatusGeometryRecord | None,
    *required: str,
) -> tuple[str, ...]:
    """Return explicit blockers instead of inferring missing apparatus geometry."""
    if record is None:
        return ("apparatus-geometry-unavailable",)
    available = record.geometry.capabilities
    return tuple(f"missing-geometry:{value}" for value in required if value not in available)


def _orientation(a: ImagePoint, b: ImagePoint, c: ImagePoint) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _point_segment_distance(point: ImagePoint, start: ImagePoint, end: ImagePoint) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 0:
        return point.distance_to(start)
    projection = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
    projection = min(1.0, max(0.0, projection))
    nearest = ImagePoint(start.x + projection * dx, start.y + projection * dy)
    return point.distance_to(nearest)


def _segments_intersect(a: ImagePoint, b: ImagePoint, c: ImagePoint, d: ImagePoint) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    epsilon = 1e-12
    if (
        ((ab_c > epsilon and ab_d < -epsilon) or (ab_c < -epsilon and ab_d > epsilon))
        and ((cd_a > epsilon and cd_b < -epsilon) or (cd_a < -epsilon and cd_b > epsilon))
    ):
        return True
    return False


def _polygon_self_intersects(vertices: tuple[ImagePoint, ...]) -> bool:
    count = len(vertices)
    edges = [(vertices[index], vertices[(index + 1) % count]) for index in range(count)]
    for left_index, (a, b) in enumerate(edges):
        for right_index in range(left_index + 1, count):
            if right_index == left_index:
                continue
            if right_index == (left_index + 1) % count:
                continue
            if left_index == 0 and right_index == count - 1:
                continue
            c, d = edges[right_index]
            if _segments_intersect(a, b, c, d):
                return True
    return False
