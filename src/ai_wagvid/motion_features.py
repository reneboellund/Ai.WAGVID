"""Deterministic temporal features between pose inference and model interpretation."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .domain import Provenance, TimeRange
from .perception import ContactState, MotionObservation, PoseFrame
from .pose_processing import keypoint_map


@dataclass(frozen=True)
class ActivitySegment:
    segment_id: str
    interval: TimeRange
    camera_id: str
    peak_motion: float
    mean_motion: float
    evidence_frame_ids: tuple[str, ...]


def frame_id(frame: PoseFrame) -> str:
    return f"{frame.camera_id}:{frame.timestamp_s:.6f}"


def _midpoint(frame: PoseFrame, left: str, right: str) -> tuple[float, float, float] | None:
    points = keypoint_map(frame)
    if left not in points or right not in points:
        return None
    first, second = points[left], points[right]
    return (
        (first.x + second.x) / 2,
        (first.y + second.y) / 2,
        min(first.confidence, second.confidence),
    )


def pose_motion(previous: PoseFrame, current: PoseFrame, *, min_confidence: float = 0.2) -> float | None:
    """Median-like robust displacement per second over mutually visible keypoints."""

    if previous.camera_id != current.camera_id:
        raise ValueError("motion requires frames from one camera")
    elapsed = current.timestamp_s - previous.timestamp_s
    if elapsed <= 0:
        raise ValueError("motion timestamps must increase")
    old = keypoint_map(previous)
    values = sorted(
        math.hypot(point.x - old[name].x, point.y - old[name].y) / elapsed
        for name, point in keypoint_map(current).items()
        if name in old and min(point.confidence, old[name].confidence) >= min_confidence
    )
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def body_axis_degrees(frame: PoseFrame, *, min_confidence: float = 0.2) -> float | None:
    hips = _midpoint(frame, "left_hip", "right_hip")
    shoulders = _midpoint(frame, "left_shoulder", "right_shoulder")
    if not hips or not shoulders or min(hips[2], shoulders[2]) < min_confidence:
        return None
    return math.degrees(math.atan2(shoulders[1] - hips[1], shoulders[0] - hips[0]))


def segment_activity(
    frames: Sequence[PoseFrame], *, start_threshold: float = 0.12,
    stop_threshold: float = 0.06, quiet_seconds: float = 0.5,
) -> tuple[ActivitySegment, ...]:
    """Hysteresis segmenter suitable as a baseline and motion-trigger reference."""

    if start_threshold <= stop_threshold or stop_threshold < 0 or quiet_seconds < 0:
        raise ValueError("activity thresholds are invalid")
    by_camera: dict[str, list[PoseFrame]] = defaultdict(list)
    for frame in frames:
        by_camera[frame.camera_id].append(frame)
    output: list[ActivitySegment] = []
    for camera_id, camera_frames in sorted(by_camera.items()):
        camera_frames.sort(key=lambda item: item.timestamp_s)
        active_start: int | None = None
        quiet_since: float | None = None
        energies: list[tuple[int, float]] = []
        for index, (previous, current) in enumerate(pairwise(camera_frames), start=1):
            energy = pose_motion(previous, current)
            value = energy or 0.0
            if active_start is None and value >= start_threshold:
                active_start = index - 1
                energies = [(index, value)]
                quiet_since = None
                continue
            if active_start is None:
                continue
            energies.append((index, value))
            if value <= stop_threshold:
                quiet_since = quiet_since or current.timestamp_s
            else:
                quiet_since = None
            if quiet_since is not None and current.timestamp_s - quiet_since >= quiet_seconds:
                end_index = max(active_start + 1, index - 1)
                output.append(_activity(camera_id, camera_frames, active_start, end_index, energies))
                active_start, quiet_since, energies = None, None, []
        if active_start is not None:
            output.append(
                _activity(camera_id, camera_frames, active_start, len(camera_frames) - 1, energies)
            )
    return tuple(output)


def _activity(
    camera_id: str, frames: Sequence[PoseFrame], start: int, end: int,
    energies: Sequence[tuple[int, float]],
) -> ActivitySegment:
    values = [value for index, value in energies if start <= index <= end] or [0.0]
    evidence = tuple(frame_id(frame) for frame in frames[start : end + 1])
    return ActivitySegment(
        f"activity:{camera_id}:{frames[start].timestamp_s:.3f}",
        TimeRange(frames[start].timestamp_s, frames[end].timestamp_s), camera_id,
        max(values), sum(values) / len(values), evidence,
    )


def extract_motion_observations(
    frames: Sequence[PoseFrame], *, source_id: str, producer: str,
    producer_version: str, config_digest: str | None = None,
    support_y: float | None = None, contact_tolerance: float = 0.04,
) -> tuple[MotionObservation, ...]:
    """Create auditable geometry observations; contact remains a candidate state."""

    provenance = Provenance(source_id, producer, producer_version, config_digest)
    observations: list[MotionObservation] = []
    for frame in frames:
        axis = body_axis_degrees(frame)
        if axis is not None:
            observations.append(MotionObservation(
                f"axis:{frame_id(frame)}", "body_axis_2d",
                TimeRange(frame.timestamp_s, frame.timestamp_s), None, (frame_id(frame),),
                {"degrees": axis, "reference": "image_x_axis"}, provenance,
            ))
        if support_y is None:
            continue
        points = keypoint_map(frame)
        ankles = [points[name] for name in ("left_ankle", "right_ankle") if name in points]
        visible = [point for point in ankles if point.confidence >= 0.2]
        if not visible:
            state, confidence = ContactState.UNKNOWN, None
        else:
            distance = min(abs(point.y - support_y) for point in visible)
            state = ContactState.POSSIBLE_CONTACT if distance <= contact_tolerance else ContactState.FLIGHT
            confidence = min(point.confidence for point in visible)
        observations.append(MotionObservation(
            f"support:{frame_id(frame)}", "support_contact_candidate",
            TimeRange(frame.timestamp_s, frame.timestamp_s), confidence, (frame_id(frame),),
            {"state": state.value, "support_y": support_y, "tolerance": contact_tolerance},
            provenance,
        ))
    return tuple(observations)
