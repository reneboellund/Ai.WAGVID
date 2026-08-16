"""FFprobe parsing and FFmpeg command plans without executing external tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VideoStreamProbe:
    codec: str
    width: int
    height: int
    average_fps: Fraction | None
    nominal_fps: Fraction | None
    duration_s: float | None
    rotation_degrees: int
    pixel_format: str | None

    @property
    def likely_variable_frame_rate(self) -> bool:
        return bool(
            self.average_fps
            and self.nominal_fps
            and abs(float(self.average_fps) - float(self.nominal_fps)) > 0.01
        )


@dataclass(frozen=True)
class MediaProbe:
    format_name: str
    duration_s: float | None
    size_bytes: int | None
    video: VideoStreamProbe
    audio_streams: int


def _fraction(value: Any) -> Fraction | None:
    if not value or value == "0/0":
        return None
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return result if result > 0 else None


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "N/A", "") else None
    except (TypeError, ValueError):
        return None


def _rotation(stream: dict[str, Any]) -> int:
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        try:
            return int(tags["rotate"]) % 360
        except (TypeError, ValueError):
            pass
    for item in stream.get("side_data_list") or []:
        if "rotation" in item:
            try:
                return int(item["rotation"]) % 360
            except (TypeError, ValueError):
                pass
    return 0


def parse_ffprobe(payload: str | dict[str, Any]) -> MediaProbe:
    data = json.loads(payload) if isinstance(payload, str) else payload
    streams = data.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not video_streams:
        raise ValueError("media has no video stream")
    stream = video_streams[0]
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("video stream has invalid dimensions")
    format_data = data.get("format") or {}
    video = VideoStreamProbe(
        codec=str(stream.get("codec_name") or "unknown"),
        width=width,
        height=height,
        average_fps=_fraction(stream.get("avg_frame_rate")),
        nominal_fps=_fraction(stream.get("r_frame_rate")),
        duration_s=_optional_float(stream.get("duration")),
        rotation_degrees=_rotation(stream),
        pixel_format=stream.get("pix_fmt"),
    )
    size = format_data.get("size")
    return MediaProbe(
        format_name=str(format_data.get("format_name") or "unknown"),
        duration_s=_optional_float(format_data.get("duration")) or video.duration_s,
        size_bytes=int(size) if size not in (None, "N/A", "") else None,
        video=video,
        audio_streams=sum(stream.get("codec_type") == "audio" for stream in streams),
    )


def ffprobe_command(source: Path) -> tuple[str, ...]:
    return (
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(source),
    )


def analysis_proxy_command(source: Path, destination: Path) -> tuple[str, ...]:
    if source.resolve() == destination.resolve():
        raise ValueError("analysis proxy must not overwrite the immutable source")
    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-fps_mode",
        "passthrough",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(destination),
    )
