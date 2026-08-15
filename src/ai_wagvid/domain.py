from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence


class Apparatus(str, Enum):
    VT = "VT"
    UB = "UB"
    BB = "BB"
    FX = "FX"


class AnalysisState(str, Enum):
    DRAFT_AI = "DRAFT_AI"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    PANEL_CONFIRMED = "PANEL_CONFIRMED"
    FROZEN = "FROZEN"
    INVALID_INPUT = "INVALID_INPUT"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"


@dataclass(frozen=True)
class TimeRange:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.end_s < self.start_s:
            raise ValueError("Invalid time range")


@dataclass(frozen=True)
class Provenance:
    source_id: str
    producer: str
    producer_version: str
    config_digest: str | None = None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    kind: str
    interval: TimeRange
    confidence: float | None
    payload: dict[str, Any]
    provenance: Provenance
    camera_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ElementCandidate:
    element_id: str
    confidence: float
    supporting_observation_ids: tuple[str, ...]


@dataclass(frozen=True)
class SegmentInterpretation:
    segment_id: str
    apparatus: Apparatus
    candidates: tuple[ElementCandidate, ...]
    unknown_probability: float
    review_required: bool


@dataclass(frozen=True)
class RuleApplication:
    rule_id: str
    rulepack_id: str
    status: str
    consequence: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreLedger:
    rulepack_id: str
    d_components: tuple[RuleApplication, ...] = ()
    execution_components: tuple[RuleApplication, ...] = ()
    artistry_components: tuple[RuleApplication, ...] = ()
    neutral_components: tuple[RuleApplication, ...] = ()
    d_score: float | None = None
    e_score: float | None = None
    final_score: float | None = None
    unresolved: tuple[str, ...] = ()


class RuleEngine(Protocol):
    """Deterministic boundary. ML observations enter; score rules do not call ML."""

    @property
    def rulepack_id(self) -> str: ...

    def evaluate(
        self,
        apparatus: Apparatus,
        accepted_facts: Sequence[Observation | SegmentInterpretation],
    ) -> ScoreLedger: ...
