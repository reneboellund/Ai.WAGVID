"""Pose-specific, slice-aware metrics for frozen rights-cleared validation sets."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any


@dataclass(frozen=True)
class KeypointEvaluation:
    name: str
    predicted_xy: tuple[float, float] | None
    expected_xy: tuple[float, float] | None
    predicted_confidence: float

    def __post_init__(self) -> None:
        if not 0 <= self.predicted_confidence <= 1:
            raise ValueError("predicted confidence must be between 0 and 1")


@dataclass(frozen=True)
class PoseBenchmarkCase:
    case_id: str
    apparatus: str
    camera_condition: str
    normalization_length: float
    keypoints: tuple[KeypointEvaluation, ...]
    inference_ms: float | None = None
    peak_ram_mb: float | None = None
    peak_vram_mb: float | None = None
    slices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id or not self.apparatus or not self.camera_condition:
            raise ValueError("pose case identity and slices are required")
        if self.normalization_length <= 0 or not self.keypoints:
            raise ValueError("pose case requires a positive normalization and keypoints")


def _case_metrics(cases: Sequence[PoseBenchmarkCase], threshold: float) -> dict[str, Any]:
    distances: list[float] = []
    visibility_errors: list[float] = []
    expected_count = detected_expected = unexpected_count = 0
    for case in cases:
        for point in case.keypoints:
            expected = point.expected_xy is not None
            predicted = point.predicted_xy is not None
            visibility_errors.append(abs(point.predicted_confidence - float(expected)))
            if expected:
                expected_count += 1
                if predicted:
                    detected_expected += 1
                    distances.append(
                        math.dist(point.predicted_xy, point.expected_xy) / case.normalization_length
                    )
            elif predicted:
                unexpected_count += 1
    inference = [case.inference_ms for case in cases if case.inference_ms is not None]
    ram = [case.peak_ram_mb for case in cases if case.peak_ram_mb is not None]
    vram = [case.peak_vram_mb for case in cases if case.peak_vram_mb is not None]
    return {
        "case_count": len(cases),
        "expected_keypoint_count": expected_count,
        "detected_expected_rate": detected_expected / expected_count if expected_count else None,
        "unexpected_keypoint_count": unexpected_count,
        "mean_normalized_error": fmean(distances) if distances else None,
        "pck": sum(distance <= threshold for distance in distances) / len(distances) if distances else None,
        "mean_visibility_calibration_error": fmean(visibility_errors),
        "mean_inference_ms": fmean(inference) if inference else None,
        "peak_ram_mb": max(ram) if ram else None,
        "peak_vram_mb": max(vram) if vram else None,
    }


def evaluate_pose_benchmark(
    cases: Sequence[PoseBenchmarkCase], *, pck_threshold: float = 0.2,
) -> dict[str, Any]:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("pose benchmark cases must be non-empty with unique IDs")
    if not 0 < pck_threshold <= 1:
        raise ValueError("PCK threshold must be between zero and one")
    slices: dict[str, list[PoseBenchmarkCase]] = defaultdict(list)
    for case in cases:
        slices[f"apparatus:{case.apparatus}"].append(case)
        slices[f"camera:{case.camera_condition}"].append(case)
        for name in case.slices:
            slices[name].append(case)
    return {
        "schema": "ai.wagvid.pose-benchmark-report.v1",
        "parameters": {"pck_threshold": pck_threshold},
        "overall": _case_metrics(cases, pck_threshold),
        "slices": {
            name: _case_metrics(items, pck_threshold) for name, items in sorted(slices.items())
        },
        "cases": [asdict(case) for case in cases],
    }
