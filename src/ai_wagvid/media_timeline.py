"""Canonical media timeline preserving source timestamps and uncertainty."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any, BinaryIO


@dataclass(frozen=True)
class FrameTimestamp:
    frame_index: int
    pts: int | None
    dts: int | None
    best_effort_timestamp: int
    duration_ticks: int | None
    key_frame: bool

    def __post_init__(self) -> None:
        if self.frame_index < 0:
            raise ValueError("frame index cannot be negative")


@dataclass(frozen=True)
class TimelineDiagnostics:
    frame_count: int
    duration_s: float
    effective_fps: float | None
    variable_frame_rate: bool
    duplicate_timestamp_indices: tuple[int, ...]
    non_monotonic_indices: tuple[int, ...]
    suspected_gap_indices: tuple[int, ...]


@dataclass(frozen=True)
class CanonicalTimeline:
    source_sha256: str
    stream_index: int
    time_base: Fraction
    frames: tuple[FrameTimestamp, ...]
    diagnostics: TimelineDiagnostics

    def timestamp_s(self, frame_index: int) -> float:
        try:
            frame = self.frames[frame_index]
        except IndexError as error:
            raise ValueError("frame index outside timeline") from error
        if frame.frame_index != frame_index:
            raise ValueError("timeline frame indices are not contiguous")
        return float(frame.best_effort_timestamp * self.time_base)

    def frame_at_or_before(self, timestamp_s: float) -> FrameTimestamp:
        if timestamp_s < 0:
            raise ValueError("timestamp cannot be negative")
        eligible = [
            frame for frame in self.frames
            if float(frame.best_effort_timestamp * self.time_base) <= timestamp_s
        ]
        return eligible[-1] if eligible else self.frames[0]

    @property
    def digest(self) -> str:
        payload = {
            "source_sha256": self.source_sha256,
            "stream_index": self.stream_index,
            "time_base": str(self.time_base),
            "frames": [asdict(frame) for frame in self.frames],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def sha256_stream(source: BinaryIO) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def sha256_file(path: Path) -> tuple[str, int]:
    with path.open("rb") as source:
        return sha256_stream(source)


def build_timeline(
    *, source_sha256: str, time_base: Fraction, frames: Iterable[FrameTimestamp],
    stream_index: int = 0, gap_factor: float = 1.8, vfr_tolerance: float = 0.05,
) -> CanonicalTimeline:
    ordered = tuple(frames)
    if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256):
        raise ValueError("source_sha256 must be lowercase hexadecimal")
    if time_base <= 0 or stream_index < 0 or gap_factor <= 1 or vfr_tolerance < 0:
        raise ValueError("invalid timeline parameters")
    if not ordered or tuple(item.frame_index for item in ordered) != tuple(range(len(ordered))):
        raise ValueError("timeline requires contiguous frame indices")
    ticks = [item.best_effort_timestamp for item in ordered]
    deltas = [current - previous for previous, current in pairwise(ticks)]
    positive = [delta for delta in deltas if delta > 0]
    stable_candidates = sorted(positive)[: max(1, (len(positive) + 1) // 2)]
    nominal = median(stable_candidates) if stable_candidates else None
    duplicates = tuple(index for index, delta in enumerate(deltas, start=1) if delta == 0)
    backwards = tuple(index for index, delta in enumerate(deltas, start=1) if delta < 0)
    gaps = tuple(
        index for index, delta in enumerate(deltas, start=1)
        if nominal is not None and delta > nominal * gap_factor
    )
    vfr = bool(
        nominal is not None
        and any(abs(delta - nominal) / nominal > vfr_tolerance for delta in positive)
    )
    duration_ticks = ticks[-1] - ticks[0]
    duration = float(duration_ticks * time_base)
    effective_fps = (len(ordered) - 1) / duration if duration > 0 and len(ordered) > 1 else None
    diagnostics = TimelineDiagnostics(
        len(ordered), duration, effective_fps, vfr, duplicates, backwards, gaps
    )
    return CanonicalTimeline(source_sha256, stream_index, time_base, ordered, diagnostics)


def parse_ffprobe_frames(
    payload: str | Mapping[str, Any], *, source_sha256: str, stream_index: int = 0,
) -> CanonicalTimeline:
    data = json.loads(payload) if isinstance(payload, str) else payload
    streams = [item for item in data.get("streams", []) if item.get("codec_type") == "video"]
    if stream_index >= len(streams):
        raise ValueError("requested video stream is unavailable")
    try:
        time_base = Fraction(streams[stream_index]["time_base"])
    except (KeyError, ValueError, ZeroDivisionError) as error:
        raise ValueError("video stream has invalid time_base") from error
    source_frames = [
        item for item in data.get("frames", [])
        if item.get("media_type") in (None, "video") and int(item.get("stream_index", stream_index)) == stream_index
    ]
    frames = []
    for index, item in enumerate(source_frames):
        best = item.get("best_effort_timestamp", item.get("pts"))
        if best is None:
            raise ValueError(f"frame {index} has no recoverable timestamp")
        frames.append(FrameTimestamp(
            index,
            int(item["pts"]) if item.get("pts") is not None else None,
            int(item["pkt_dts"]) if item.get("pkt_dts") is not None else None,
            int(best),
            int(item["duration"]) if item.get("duration") is not None else None,
            bool(int(item.get("key_frame", 0))),
        ))
    return build_timeline(
        source_sha256=source_sha256, time_base=time_base, frames=frames,
        stream_index=stream_index,
    )
