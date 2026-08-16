"""Model-neutral contracts for temporal localization and skill candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .domain import Apparatus, Provenance, TimeRange
from .perception import PerceptionBundle


@dataclass(frozen=True)
class SkillAlternative:
    label_id: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("skill confidence must be between 0 and 1")


@dataclass(frozen=True)
class ActionSegment:
    segment_id: str
    interval: TimeRange
    apparatus: Apparatus
    alternatives: tuple[SkillAlternative, ...]
    unknown_probability: float
    provenance: Provenance

    def __post_init__(self) -> None:
        if not 0 <= self.unknown_probability <= 1:
            raise ValueError("unknown probability must be between 0 and 1")
        confidences = [item.confidence for item in self.alternatives]
        if confidences != sorted(confidences, reverse=True):
            raise ValueError("skill alternatives must be confidence-ranked")
        if sum(confidences) + self.unknown_probability > 1.000001:
            raise ValueError("skill and unknown probabilities cannot exceed 1")


class TemporalActionModel(Protocol):
    """Adapter boundary for MMAction2/FineGym/Gym288/OSL-style models."""

    @property
    def model_id(self) -> str: ...

    def detect(
        self, *, perception: PerceptionBundle, apparatus: Apparatus
    ) -> tuple[ActionSegment, ...]: ...
