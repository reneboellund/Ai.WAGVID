"""Deterministic benchmark evaluators for apparatus model validation.

These helpers calculate reproducible component metrics from rights-cleared annotated fixtures.
They do not define promotion thresholds; thresholds remain predeclared in the benchmark manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


class ApparatusBenchmarkError(ValueError):
    pass


@dataclass(frozen=True)
class RankedIdentityExample:
    example_id: str
    expected_element_id: str | None
    ranked_element_ids: tuple[str, ...]
    unknown_ood_milli: int

    def __post_init__(self) -> None:
        if not self.example_id:
            raise ApparatusBenchmarkError("identity example_id is required")
        if len(self.ranked_element_ids) != len(set(self.ranked_element_ids)):
            raise ApparatusBenchmarkError("ranked identity predictions must be unique")
        if any(not value for value in self.ranked_element_ids):
            raise ApparatusBenchmarkError("ranked identity predictions cannot be empty strings")
        if isinstance(self.unknown_ood_milli, bool) or not isinstance(self.unknown_ood_milli, int) or not 0 <= self.unknown_ood_milli <= 1000:
            raise ApparatusBenchmarkError("unknown_ood_milli must be integer [0, 1000]")


@dataclass(frozen=True)
class IdentityMetrics:
    sample_count: int
    known_count: int
    ood_count: int
    top1_accuracy_milli: int | None
    topk_recall_milli: int | None
    ood_detection_tpr_milli: int | None
    known_false_ood_rate_milli: int | None


@dataclass(frozen=True)
class TimingExample:
    example_id: str
    reference_ms: int
    predicted_ms: int | None

    def __post_init__(self) -> None:
        if not self.example_id:
            raise ApparatusBenchmarkError("timing example_id is required")
        if isinstance(self.reference_ms, bool) or not isinstance(self.reference_ms, int) or self.reference_ms < 0:
            raise ApparatusBenchmarkError("reference_ms must be non-negative integer")
        if self.predicted_ms is not None and (isinstance(self.predicted_ms, bool) or not isinstance(self.predicted_ms, int) or self.predicted_ms < 0):
            raise ApparatusBenchmarkError("predicted_ms must be non-negative integer or None")


@dataclass(frozen=True)
class TimingMetrics:
    sample_count: int
    detected_count: int
    missed_count: int
    detection_recall_milli: int
    mean_absolute_error_ms: int | None
    median_absolute_error_ms: int | None
    max_absolute_error_ms: int | None


@dataclass(frozen=True)
class StateExample:
    example_id: str
    expected_state: str
    predicted_state: str

    def __post_init__(self) -> None:
        if not self.example_id or not self.expected_state or not self.predicted_state:
            raise ApparatusBenchmarkError("state example requires id/expected/predicted")


@dataclass(frozen=True)
class StateAgreementMetrics:
    sample_count: int
    exact_agreement_milli: int
    mismatches: tuple[tuple[str, str, str], ...]


def evaluate_ranked_identity(
    examples: tuple[RankedIdentityExample, ...],
    *,
    top_k: int,
    ood_threshold_milli: int,
) -> IdentityMetrics:
    if not examples:
        raise ApparatusBenchmarkError("identity benchmark requires examples")
    if top_k < 1:
        raise ApparatusBenchmarkError("top_k must be positive")
    if not 0 <= ood_threshold_milli <= 1000:
        raise ApparatusBenchmarkError("OOD threshold must be [0, 1000]")

    known = tuple(item for item in examples if item.expected_element_id is not None)
    ood = tuple(item for item in examples if item.expected_element_id is None)
    top1_hits = sum(bool(item.ranked_element_ids) and item.ranked_element_ids[0] == item.expected_element_id for item in known)
    topk_hits = sum(item.expected_element_id in item.ranked_element_ids[:top_k] for item in known)
    ood_hits = sum(item.unknown_ood_milli >= ood_threshold_milli for item in ood)
    false_ood = sum(item.unknown_ood_milli >= ood_threshold_milli for item in known)

    return IdentityMetrics(
        sample_count=len(examples),
        known_count=len(known),
        ood_count=len(ood),
        top1_accuracy_milli=_ratio_milli(top1_hits, len(known)) if known else None,
        topk_recall_milli=_ratio_milli(topk_hits, len(known)) if known else None,
        ood_detection_tpr_milli=_ratio_milli(ood_hits, len(ood)) if ood else None,
        known_false_ood_rate_milli=_ratio_milli(false_ood, len(known)) if known else None,
    )


def evaluate_timing(examples: tuple[TimingExample, ...]) -> TimingMetrics:
    if not examples:
        raise ApparatusBenchmarkError("timing benchmark requires examples")
    detected = tuple(item for item in examples if item.predicted_ms is not None)
    errors = tuple(abs(item.predicted_ms - item.reference_ms) for item in detected if item.predicted_ms is not None)
    return TimingMetrics(
        sample_count=len(examples),
        detected_count=len(detected),
        missed_count=len(examples) - len(detected),
        detection_recall_milli=_ratio_milli(len(detected), len(examples)),
        mean_absolute_error_ms=(sum(errors) + len(errors) // 2) // len(errors) if errors else None,
        median_absolute_error_ms=int(median(errors)) if errors else None,
        max_absolute_error_ms=max(errors) if errors else None,
    )


def evaluate_state_agreement(examples: tuple[StateExample, ...]) -> StateAgreementMetrics:
    if not examples:
        raise ApparatusBenchmarkError("state benchmark requires examples")
    mismatches = tuple(
        (item.example_id, item.expected_state, item.predicted_state)
        for item in examples
        if item.expected_state != item.predicted_state
    )
    return StateAgreementMetrics(
        sample_count=len(examples),
        exact_agreement_milli=_ratio_milli(len(examples) - len(mismatches), len(examples)),
        mismatches=mismatches,
    )


def _ratio_milli(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ApparatusBenchmarkError("ratio denominator must be positive")
    return (numerator * 1000 + denominator // 2) // denominator
