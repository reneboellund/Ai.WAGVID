"""Contracts that interpret motion observations as gymnastics candidates.

This layer ranks alternatives and preserves unknown probability. It never calculates a score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .domain import Apparatus
from .perception import PerceptionBundle


@dataclass(frozen=True)
class ElementAlternative:
    element_id: str
    confidence: float
    distinguishing_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("element confidence must be between 0 and 1")


@dataclass(frozen=True)
class ElementInterpretation:
    segment_id: str
    apparatus: Apparatus
    alternatives: tuple[ElementAlternative, ...]
    unknown_probability: float
    supporting_observation_ids: tuple[str, ...]
    interpreter_id: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.unknown_probability <= 1.0:
            raise ValueError("unknown_probability must be between 0 and 1")
        confidences = [candidate.confidence for candidate in self.alternatives]
        if confidences != sorted(confidences, reverse=True):
            raise ValueError("element alternatives must be ranked by descending confidence")
        if sum(confidences) + self.unknown_probability > 1.000001:
            raise ValueError("candidate and unknown probabilities cannot exceed 1")

    @property
    def needs_review(self) -> bool:
        return (
            not self.alternatives
            or self.unknown_probability >= 0.2
            or self.alternatives[0].confidence < 0.8
        )


class GymnasticsInterpreter(Protocol):
    """Replaceable temporal interpretation model; scoring remains a separate boundary."""

    @property
    def interpreter_id(self) -> str: ...

    def interpret(
        self,
        *,
        perception: PerceptionBundle,
        rulepack_id: str,
    ) -> tuple[ElementInterpretation, ...]: ...
