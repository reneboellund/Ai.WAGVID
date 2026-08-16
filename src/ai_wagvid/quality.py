"""Advisory Action Quality Assessment contracts.

AQA is an independent research signal. It cannot populate the deterministic score ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .domain import Apparatus, Provenance


@dataclass(frozen=True)
class QualityAssessment:
    model_id: str
    apparatus: Apparatus
    normalized_quality: float
    calibration_id: str
    confidence: float | None
    provenance: Provenance
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.normalized_quality <= 10:
            raise ValueError("normalized advisory quality must be between 0 and 10")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("quality confidence must be between 0 and 1")
        if not self.calibration_id:
            raise ValueError("AQA output requires a calibration identity")


class ActionQualityModel(Protocol):
    @property
    def model_id(self) -> str: ...

    def assess(self, *, media_id: str, apparatus: Apparatus) -> QualityAssessment: ...
