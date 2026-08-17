"""Final apparatus promotion wrapper including rulepack release readiness."""

from __future__ import annotations

from dataclasses import dataclass

from .apparatus_promotion import (
    ApparatusAcceptedFacts,
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    ApparatusPromotionDecision,
    ApparatusRulepackBinding,
    PromotionStatus,
    evaluate_apparatus_promotion,
)
from .dscore import DScoreLedger
from .rulepack_promotion import RulepackReadiness


@dataclass(frozen=True)
class ValidatedApparatusPromotionDecision:
    base: ApparatusPromotionDecision
    rulepack_readiness: RulepackReadiness
    status: PromotionStatus
    blockers: tuple[str, ...]


def evaluate_validated_apparatus_promotion(
    *,
    model: ApparatusModelBundle,
    binding: ApparatusRulepackBinding,
    accepted_facts: ApparatusAcceptedFacts,
    benchmark: ApparatusBenchmarkReport,
    dscore_ledger: DScoreLedger | None,
    rulepack_readiness: RulepackReadiness,
) -> ValidatedApparatusPromotionDecision:
    base = evaluate_apparatus_promotion(
        model=model,
        binding=binding,
        accepted_facts=accepted_facts,
        benchmark=benchmark,
        dscore_ledger=dscore_ledger,
    )
    blockers = list(base.blockers)
    if not rulepack_readiness.ready:
        blockers.append("rulepack-not-release-ready")
        blockers.extend(f"rulepack:{item}" for item in rulepack_readiness.blockers)
    if rulepack_readiness.rulepack_id != binding.rulepack_id:
        blockers.append("rulepack-readiness-id-mismatch")
    if rulepack_readiness.manifest_sha256 is None:
        blockers.append("rulepack-manifest-digest-missing")
    normalized = tuple(sorted(set(blockers)))
    return ValidatedApparatusPromotionDecision(
        base=base,
        rulepack_readiness=rulepack_readiness,
        status=PromotionStatus.BLOCKED if normalized else base.status,
        blockers=normalized,
    )
