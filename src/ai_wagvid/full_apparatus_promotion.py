"""Final model + rulepack + ledger + benchmark promotion gate for apparatus analysis."""

from __future__ import annotations

from dataclasses import dataclass

from .apparatus_promotion import (
    ApparatusAcceptedFacts,
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    ApparatusRulepackBinding,
    PromotionStatus,
)
from .dscore import DScoreLedger
from .model_readiness import ProfileReadiness
from .rulepack_promotion import RulepackReadiness
from .validated_apparatus_promotion import (
    ValidatedApparatusPromotionDecision,
    evaluate_validated_apparatus_promotion,
)


@dataclass(frozen=True)
class FullApparatusPromotionDecision:
    validated: ValidatedApparatusPromotionDecision
    model_profile_readiness: ProfileReadiness
    status: PromotionStatus
    blockers: tuple[str, ...]


def evaluate_full_apparatus_promotion(
    *,
    model: ApparatusModelBundle,
    model_profile_readiness: ProfileReadiness,
    binding: ApparatusRulepackBinding,
    accepted_facts: ApparatusAcceptedFacts,
    benchmark: ApparatusBenchmarkReport,
    dscore_ledger: DScoreLedger | None,
    rulepack_readiness: RulepackReadiness,
) -> FullApparatusPromotionDecision:
    validated = evaluate_validated_apparatus_promotion(
        model=model,
        binding=binding,
        accepted_facts=accepted_facts,
        benchmark=benchmark,
        dscore_ledger=dscore_ledger,
        rulepack_readiness=rulepack_readiness,
    )
    blockers = list(validated.blockers)
    if not model_profile_readiness.ready:
        blockers.append("model-profile-not-benchmark-ready")
        blockers.extend(f"model:{item}" for item in model_profile_readiness.blockers)
    normalized = tuple(sorted(set(blockers)))
    return FullApparatusPromotionDecision(
        validated=validated,
        model_profile_readiness=model_profile_readiness,
        status=PromotionStatus.BLOCKED if normalized else validated.status,
        blockers=normalized,
    )
