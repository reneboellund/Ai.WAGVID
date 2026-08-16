"""Official-versus-model score comparison without treating either side as infallible."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ScoreLine:
    d_score: Decimal | None
    e_score: Decimal | None
    neutral: Decimal | None
    final_score: Decimal | None


@dataclass(frozen=True)
class ScoreDifference:
    field: str
    official: Decimal
    proposed: Decimal
    delta: Decimal
    exceeds_threshold: bool


@dataclass(frozen=True)
class ScoreComparison:
    differences: tuple[ScoreDifference, ...]
    missing_fields: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.missing_fields) or any(item.exceeds_threshold for item in self.differences)


def compare_scores(
    official: ScoreLine,
    proposed: ScoreLine,
    *,
    threshold: Decimal = Decimal("0.100"),
) -> ScoreComparison:
    if threshold < 0:
        raise ValueError("comparison threshold cannot be negative")
    differences = []
    missing = []
    for field in ("d_score", "e_score", "neutral", "final_score"):
        official_value = getattr(official, field)
        proposed_value = getattr(proposed, field)
        if official_value is None or proposed_value is None:
            missing.append(field)
            continue
        delta = proposed_value - official_value
        differences.append(
            ScoreDifference(
                field=field,
                official=official_value,
                proposed=proposed_value,
                delta=delta,
                exceeds_threshold=abs(delta) >= threshold,
            )
        )
    return ScoreComparison(tuple(differences), tuple(missing))
