"""Deterministic pose processing independent of model frameworks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from .perception import Keypoint, PoseFrame


@dataclass(frozen=True)
class JointAngle:
    name: str
    degrees: float
    confidence: float
    vertex: str


COMMON_JOINTS: dict[str, tuple[str, str, str]] = {
    "left_elbow": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_shoulder": ("left_elbow", "left_shoulder", "left_hip"),
    "right_shoulder": ("right_elbow", "right_shoulder", "right_hip"),
    "left_hip": ("left_shoulder", "left_hip", "left_knee"),
    "right_hip": ("right_shoulder", "right_hip", "right_knee"),
    "left_knee": ("left_hip", "left_knee", "left_ankle"),
    "right_knee": ("right_hip", "right_knee", "right_ankle"),
}


def keypoint_map(frame: PoseFrame) -> dict[str, Keypoint]:
    result: dict[str, Keypoint] = {}
    for point in frame.keypoints:
        if point.name in result:
            raise ValueError(f"duplicate keypoint name: {point.name}")
        result[point.name] = point
    return result


def _midpoint(left: Keypoint, right: Keypoint, name: str) -> Keypoint:
    z = None if left.z is None or right.z is None else (left.z + right.z) / 2
    return Keypoint(
        name,
        (left.x + right.x) / 2,
        (left.y + right.y) / 2,
        min(left.confidence, right.confidence),
        z,
    )


def normalize_skeleton(frame: PoseFrame, *, min_confidence: float = 0.2) -> PoseFrame:
    """Center at hips, scale by torso and align the torso vertically."""

    points = keypoint_map(frame)
    required = ("left_hip", "right_hip", "left_shoulder", "right_shoulder")
    if any(name not in points for name in required):
        raise ValueError("normalization requires left/right hips and shoulders")
    if any(points[name].confidence < min_confidence for name in required):
        raise ValueError("normalization anchors are below confidence threshold")
    hips = _midpoint(points["left_hip"], points["right_hip"], "hip_midpoint")
    shoulders = _midpoint(
        points["left_shoulder"], points["right_shoulder"], "shoulder_midpoint"
    )
    axis_x, axis_y = shoulders.x - hips.x, shoulders.y - hips.y
    torso = math.hypot(axis_x, axis_y)
    if torso <= 1e-9:
        raise ValueError("normalization anchors define a zero-length torso")
    rotation = -math.pi / 2 - math.atan2(axis_y, axis_x)
    cosine, sine = math.cos(rotation), math.sin(rotation)
    normalized: list[Keypoint] = []
    for point in frame.keypoints:
        relative_x, relative_y = point.x - hips.x, point.y - hips.y
        x = (relative_x * cosine - relative_y * sine) / torso
        y = (relative_x * sine + relative_y * cosine) / torso
        z = None if point.z is None else (point.z - (hips.z or 0.0)) / torso
        normalized.append(Keypoint(point.name, x, y, point.confidence, z))
    return PoseFrame(frame.timestamp_s, tuple(normalized), frame.visibility, frame.camera_id)


def compute_joint_angle(
    first: Keypoint,
    vertex: Keypoint,
    third: Keypoint,
    *,
    name: str | None = None,
    min_confidence: float = 0.2,
) -> JointAngle | None:
    confidence = min(first.confidence, vertex.confidence, third.confidence)
    if confidence < min_confidence:
        return None
    vector_a = (first.x - vertex.x, first.y - vertex.y)
    vector_b = (third.x - vertex.x, third.y - vertex.y)
    length_a, length_b = math.hypot(*vector_a), math.hypot(*vector_b)
    if length_a <= 1e-9 or length_b <= 1e-9:
        return None
    cosine = (vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]) / (
        length_a * length_b
    )
    degrees = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    return JointAngle(name or vertex.name, degrees, confidence, vertex.name)


def extract_joint_angles(
    frame: PoseFrame,
    definitions: Mapping[str, tuple[str, str, str]] = COMMON_JOINTS,
    *,
    min_confidence: float = 0.2,
) -> tuple[JointAngle, ...]:
    points = keypoint_map(frame)
    angles: list[JointAngle] = []
    for name, (first, vertex, third) in definitions.items():
        if not all(point in points for point in (first, vertex, third)):
            continue
        angle = compute_joint_angle(
            points[first], points[vertex], points[third], name=name, min_confidence=min_confidence
        )
        if angle is not None:
            angles.append(angle)
    return tuple(angles)


def smooth_pose_sequence(frames: Sequence[PoseFrame], *, radius: int = 1) -> tuple[PoseFrame, ...]:
    """Apply a centered confidence-weighted average by camera and keypoint."""

    if radius < 0:
        raise ValueError("smoothing radius cannot be negative")
    if not frames or radius == 0:
        return tuple(frames)
    if any(current.timestamp_s < previous.timestamp_s for previous, current in pairwise(frames)):
        raise ValueError("pose frames must be ordered by timestamp")
    maps = [keypoint_map(frame) for frame in frames]
    smoothed: list[PoseFrame] = []
    for index, frame in enumerate(frames):
        output: list[Keypoint] = []
        for original in frame.keypoints:
            neighbours = [
                maps[item][original.name]
                for item in range(max(0, index - radius), min(len(frames), index + radius + 1))
                if frames[item].camera_id == frame.camera_id
                and original.name in maps[item]
                and maps[item][original.name].confidence > 0
            ]
            if not neighbours:
                output.append(original)
                continue
            weight = sum(point.confidence for point in neighbours)
            x = sum(point.x * point.confidence for point in neighbours) / weight
            y = sum(point.y * point.confidence for point in neighbours) / weight
            with_z = [point for point in neighbours if point.z is not None]
            z = None
            if with_z:
                z_weight = sum(point.confidence for point in with_z)
                z = sum((point.z or 0) * point.confidence for point in with_z) / z_weight
            output.append(Keypoint(original.name, x, y, original.confidence, z))
        smoothed.append(PoseFrame(frame.timestamp_s, tuple(output), frame.visibility, frame.camera_id))
    return tuple(smoothed)
