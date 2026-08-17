"""Bridge media-worker timeline artifacts to the existing FFprobe import contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .media_worker import MediaWorkerError, sha256_file


def load_worker_timeline(
    path: Path,
    *,
    expected_source_sha256: str,
    expected_artifact_sha256: str | None = None,
) -> dict:
    if expected_artifact_sha256 is not None:
        actual, _ = sha256_file(path)
        if actual != expected_artifact_sha256:
            raise MediaWorkerError("Worker timeline artifact SHA-256 mismatch")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MediaWorkerError("Worker timeline artifact is unreadable") from error
    if not isinstance(value, Mapping):
        raise MediaWorkerError("Worker timeline artifact must be a JSON object")
    if value.get("schema") != "ai.wagvid.ffprobe-frame-timeline.v1":
        raise MediaWorkerError("Unsupported worker timeline schema")
    if value.get("source_sha256") != expected_source_sha256:
        raise MediaWorkerError("Worker timeline belongs to a different source object")
    frames = value.get("frames")
    if not isinstance(frames, list) or not frames:
        raise MediaWorkerError("Worker timeline contains no frames")
    if value.get("frame_count") != len(frames):
        raise MediaWorkerError("Worker timeline frame_count does not match frame payload")
    return dict(value)


def ffprobe_import_payload(timeline: Mapping[str, object]) -> dict:
    """Return the shape accepted by the existing FFprobe-frame import path.

    Timestamps are emitted as decimal strings, matching FFprobe JSON output. The adapter does
    not invent DTS/frame-rate values that were not captured by the worker artifact.
    """
    frames = timeline.get("frames")
    if not isinstance(frames, list) or not frames:
        raise MediaWorkerError("Worker timeline contains no frames")
    result = []
    previous = float("-inf")
    for expected_index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise MediaWorkerError(f"Worker frame {expected_index} is not an object")
        if frame.get("index") != expected_index:
            raise MediaWorkerError("Worker timeline frame indices are not contiguous")
        best = float(frame["best_effort_timestamp_time"])
        if best < previous:
            raise MediaWorkerError("Worker timeline presentation timestamps are non-monotonic")
        previous = best
        item = {
            "best_effort_timestamp_time": f"{best:.9f}",
            "key_frame": 1 if bool(frame.get("key_frame")) else 0,
        }
        pts = frame.get("pts_time")
        duration = frame.get("pkt_duration_time")
        if pts is not None:
            item["pts_time"] = f"{float(pts):.9f}"
        if duration is not None:
            item["pkt_duration_time"] = f"{float(duration):.9f}"
        result.append(item)
    return {"frames": result}
