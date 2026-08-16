"""Versioned deterministic exports for model-neutral analysis contracts."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .actions import ActionSegment
from .domain import ScoreLedger
from .perception import PerceptionBundle
from .quality import QualityAssessment

ANALYSIS_EXPORT_SCHEMA_VERSION = "1.0.0"


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    return value


def build_analysis_export(
    *,
    perception: PerceptionBundle,
    segments: tuple[ActionSegment, ...] = (),
    score_ledger: ScoreLedger | None = None,
    quality: QualityAssessment | None = None,
) -> dict[str, Any]:
    if quality is not None and quality.apparatus != perception.apparatus:
        raise ValueError("AQA and perception apparatus must match")
    if any(segment.apparatus != perception.apparatus for segment in segments):
        raise ValueError("action segment and perception apparatus must match")
    return {
        "schema_version": ANALYSIS_EXPORT_SCHEMA_VERSION,
        "media_id": perception.media_id,
        "apparatus": perception.apparatus.value,
        "perception": _primitive(perception),
        "action_segments": _primitive(segments),
        "score_ledger": _primitive(score_ledger) if score_ledger else None,
        "advisory_quality": _primitive(quality) if quality else None,
    }


def analysis_export_json(**kwargs: Any) -> str:
    return json.dumps(
        build_analysis_export(**kwargs),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def pose_frames_csv(perception: PerceptionBundle) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        [
            "schema_version",
            "media_id",
            "apparatus",
            "camera_id",
            "timestamp_s",
            "visibility",
            "keypoint",
            "x",
            "y",
            "z",
            "confidence",
        ]
    )
    for frame in perception.pose_frames:
        for point in frame.keypoints:
            writer.writerow(
                [
                    ANALYSIS_EXPORT_SCHEMA_VERSION,
                    perception.media_id,
                    perception.apparatus.value,
                    frame.camera_id,
                    frame.timestamp_s,
                    frame.visibility.value,
                    point.name,
                    point.x,
                    point.y,
                    "" if point.z is None else point.z,
                    point.confidence,
                ]
            )
    return stream.getvalue()
