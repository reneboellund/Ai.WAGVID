"""Deterministic benchmark metrics for frozen gymnastics evaluation cases."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import fmean
from typing import Any


@dataclass(frozen=True)
class RankedCandidate:
    label_id: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.label_id or not 0 <= self.confidence <= 1:
            raise ValueError("candidate requires a label and confidence between 0 and 1")


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    apparatus: str
    ground_truth_label: str | None
    candidates: tuple[RankedCandidate, ...]
    unknown_probability: float
    event_timing_error_ms: float | None = None
    slices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id or not self.apparatus:
            raise ValueError("case_id and apparatus are required")
        if not 0 <= self.unknown_probability <= 1:
            raise ValueError("unknown_probability must be between 0 and 1")
        confidences = [item.confidence for item in self.candidates]
        if confidences != sorted(confidences, reverse=True):
            raise ValueError("candidates must be confidence-ranked")
        if sum(confidences) + self.unknown_probability > 1.000001:
            raise ValueError("candidate and unknown probabilities cannot exceed 1")


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    dataset_id: str
    dataset_version: str
    split: str
    model_profile: str
    model_bundle_digest: str
    software_revision: str
    rulepack_id: str | None
    started_at: datetime

    def __post_init__(self) -> None:
        required = (
            self.run_id,
            self.dataset_id,
            self.dataset_version,
            self.split,
            self.model_profile,
            self.model_bundle_digest,
            self.software_revision,
        )
        if any(not value for value in required):
            raise ValueError("benchmark run provenance is incomplete")
        if self.split not in {"validation", "test"}:
            raise ValueError("benchmark reports are restricted to validation or test splits")


def _metrics(cases: tuple[BenchmarkCase, ...], *, top_k: int, unknown_threshold: float) -> dict:
    known = [case for case in cases if case.ground_truth_label is not None]
    unknown = [case for case in cases if case.ground_truth_label is None]
    top1 = sum(
        bool(case.candidates and case.candidates[0].label_id == case.ground_truth_label)
        for case in known
    )
    topk = sum(
        case.ground_truth_label in {item.label_id for item in case.candidates[:top_k]}
        for case in known
    )
    unknown_hits = sum(case.unknown_probability >= unknown_threshold for case in unknown)
    false_unknown = sum(case.unknown_probability >= unknown_threshold for case in known)
    timings = [abs(case.event_timing_error_ms) for case in cases if case.event_timing_error_ms is not None]
    confidences_and_correctness = [
        (
            case.candidates[0].confidence if case.candidates else case.unknown_probability,
            float(
                (case.ground_truth_label is None and case.unknown_probability >= unknown_threshold)
                or (
                    case.ground_truth_label is not None
                    and bool(case.candidates)
                    and case.candidates[0].label_id == case.ground_truth_label
                )
            ),
        )
        for case in cases
    ]
    calibration_error = fmean(
        abs(confidence - correctness) for confidence, correctness in confidences_and_correctness
    )
    return {
        "case_count": len(cases),
        "known_count": len(known),
        "unknown_count": len(unknown),
        "top1_accuracy": top1 / len(known) if known else None,
        f"top{top_k}_accuracy": topk / len(known) if known else None,
        "unknown_recall": unknown_hits / len(unknown) if unknown else None,
        "false_unknown_rate": false_unknown / len(known) if known else None,
        "mean_absolute_timing_error_ms": fmean(timings) if timings else None,
        "mean_confidence_error": calibration_error,
    }


def evaluate_benchmark(
    run: BenchmarkRun,
    cases: tuple[BenchmarkCase, ...],
    *,
    top_k: int = 3,
    unknown_threshold: float = 0.5,
) -> dict[str, Any]:
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("benchmark cases must be non-empty with unique IDs")
    if top_k < 1 or not 0 <= unknown_threshold <= 1:
        raise ValueError("top_k and unknown_threshold are invalid")
    slices: dict[str, list[BenchmarkCase]] = defaultdict(list)
    for case in cases:
        slices[f"apparatus:{case.apparatus}"].append(case)
        for name in case.slices:
            slices[name].append(case)
    return {
        "schema": "ai.wagvid.benchmark-report.v1",
        "run": {**asdict(run), "started_at": run.started_at.isoformat()},
        "parameters": {"top_k": top_k, "unknown_threshold": unknown_threshold},
        "overall": _metrics(cases, top_k=top_k, unknown_threshold=unknown_threshold),
        "slices": {
            name: _metrics(tuple(items), top_k=top_k, unknown_threshold=unknown_threshold)
            for name, items in sorted(slices.items())
        },
    }
