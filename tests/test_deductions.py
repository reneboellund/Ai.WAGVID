from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.deductions import (
    AcceptedDeductionEntry,
    DecisionAction,
    DeductionCandidate,
    DeductionChannel,
    DeductionDecision,
    DeductionDecisionLedger,
    DeductionError,
    DeductionPolicy,
    DeductionRule,
    DeductionScope,
    ProposalState,
    RuleApplicability,
    SeverityRule,
    build_deduction_ledger,
    evaluate_deduction_candidate,
)
from ai_wagvid.domain import Apparatus


T0 = datetime(2026, 8, 17, 11, 0, tzinfo=UTC)
MODEL_DIGEST = "a" * 64
RULEPACK_DIGEST = "b" * 64


def policy() -> DeductionPolicy:
    # Synthetic values/criteria only; no FIG rule content is encoded in these tests.
    return DeductionPolicy(
        rulepack_id="fixture-deductions@v1",
        rulepack_digest=RULEPACK_DIGEST,
        apparatus=Apparatus.FX,
        units_per_point=10,
        rules=(
            DeductionRule(
                rule_id="fixture.execution.shape",
                channel=DeductionChannel.EXECUTION,
                criterion_id="shape-observation",
                scope=DeductionScope.ELEMENT,
                severities=(
                    SeverityRule("small", 1, "fixture.source.shape.small"),
                    SeverityRule("medium", 3, "fixture.source.shape.medium"),
                ),
                required_camera_capabilities=frozenset({"body-shape-visible"}),
                minimum_evidence_quality_milli=700,
                minimum_model_confidence_milli=800,
                source_rule_id="fixture.source.shape",
            ),
            DeductionRule(
                rule_id="fixture.artistry.criterion",
                channel=DeductionChannel.ARTISTRY,
                criterion_id="qualitative-routine-criterion",
                scope=DeductionScope.ROUTINE,
                severities=(SeverityRule("criterion-loss", 2, "fixture.source.artistry"),),
                minimum_evidence_quality_milli=600,
                minimum_model_confidence_milli=700,
                human_judgement_required=True,
                source_rule_id="fixture.source.artistry",
            ),
            DeductionRule(
                rule_id="fixture.neutral.boundary",
                channel=DeductionChannel.NEUTRAL,
                criterion_id="boundary-observation",
                scope=DeductionScope.PROCEDURAL,
                severities=(SeverityRule("boundary-loss", 1, "fixture.source.boundary"),),
                required_camera_capabilities=frozenset({"floor-boundary-visible"}),
                minimum_evidence_quality_milli=800,
                minimum_model_confidence_milli=900,
                source_rule_id="fixture.source.boundary",
            ),
        ),
    )


def candidate(
    candidate_id: str = "cand-1",
    *,
    rule_id: str = "fixture.execution.shape",
    severity: str | None = "small",
    confidence: int | None = 900,
    quality: int | None = 900,
    capabilities: frozenset[str] = frozenset({"body-shape-visible"}),
    evidence_ids: tuple[str, ...] = ("evidence-1",),
) -> DeductionCandidate:
    return DeductionCandidate(
        candidate_id=candidate_id,
        rule_id=rule_id,
        scope_ref="scope-1",
        evidence_ids=evidence_ids,
        observation_ids=(f"obs-{candidate_id}",),
        proposed_severity_id=severity,
        model_confidence_milli=confidence,
        evidence_quality_milli=quality,
        camera_ids=("cam-a",),
        camera_capabilities=capabilities,
        producer_id="fixture-detector",
        producer_digest=MODEL_DIGEST,
    )


def decision(
    proposal,
    *,
    decision_id: str = "decision-1",
    action: DecisionAction = DecisionAction.ACCEPT,
    severity: str | None = "small",
    created_at: datetime = T0,
    supersedes: str | None = None,
) -> DeductionDecision:
    return DeductionDecision(
        decision_id=decision_id,
        proposal_digest=proposal.digest,
        candidate_id=proposal.candidate_id,
        action=action,
        author_id="reviewer-a",
        created_at=created_at,
        reason="Reviewed synchronized source evidence",
        selected_severity_id=severity,
        supersedes_decision_id=supersedes,
    )


def test_high_confidence_execution_proposal_still_does_not_count_without_human_decision():
    proposal = evaluate_deduction_candidate(policy(), candidate())
    assert proposal.state is ProposalState.READY_FOR_CONFIRMATION
    assert proposal.rule_applicability is RuleApplicability.EXACT
    assert proposal.model_suggested_units == 1

    decisions = DeductionDecisionLedger(policy(), (proposal,))
    ledger = build_deduction_ledger(policy(), (proposal,), decisions)
    assert ledger.accepted == ()
    assert ledger.accepted_deduction_units == 0
    assert ledger.unresolved_candidate_ids == (proposal.candidate_id,)
    assert ledger.fully_resolved is False


def test_low_confidence_candidate_is_needs_review_not_a_guessed_deduction():
    proposal = evaluate_deduction_candidate(policy(), candidate(confidence=500))
    assert proposal.state is ProposalState.NEEDS_REVIEW
    assert proposal.rule_applicability is RuleApplicability.AMBIGUOUS
    assert "model-confidence-below-rule-threshold:500<800" in proposal.review_reasons


def test_low_evidence_quality_is_conditional_even_when_model_confidence_is_high():
    proposal = evaluate_deduction_candidate(policy(), candidate(quality=600))
    assert proposal.state is ProposalState.NEEDS_REVIEW
    assert proposal.rule_applicability is RuleApplicability.CONDITIONAL
    assert "evidence-quality-below-rule-threshold:600<700" in proposal.review_reasons


def test_missing_camera_capability_makes_boundary_candidate_unavailable_not_negative_evidence():
    proposal = evaluate_deduction_candidate(
        policy(),
        candidate(
            rule_id="fixture.neutral.boundary",
            severity="boundary-loss",
            confidence=950,
            quality=950,
            capabilities=frozenset(),
        ),
    )
    assert proposal.state is ProposalState.UNAVAILABLE
    assert proposal.rule_applicability is RuleApplicability.UNAVAILABLE
    assert proposal.missing_camera_capabilities == ("floor-boundary-visible",)
    assert "missing-camera-capability:floor-boundary-visible" in proposal.review_reasons

    decisions = DeductionDecisionLedger(policy(), (proposal,))
    with pytest.raises(DeductionError, match="unavailable proposal cannot be accepted"):
        decisions.append(decision(proposal, severity="boundary-loss"))


def test_missing_evidence_or_evidence_quality_fails_closed():
    no_evidence = evaluate_deduction_candidate(policy(), candidate(evidence_ids=()))
    assert no_evidence.state is ProposalState.UNAVAILABLE
    assert "evidence-unavailable" in no_evidence.review_reasons

    no_quality = evaluate_deduction_candidate(policy(), candidate(quality=None))
    assert no_quality.state is ProposalState.UNAVAILABLE
    assert "evidence-quality-unavailable" in no_quality.review_reasons


def test_artistry_rule_cannot_be_configured_as_machine_final_judgement():
    with pytest.raises(DeductionError, match="artistry criteria must require human judgement"):
        DeductionRule(
            rule_id="bad-artistry",
            channel=DeductionChannel.ARTISTRY,
            criterion_id="opaque-aesthetic-score",
            scope=DeductionScope.ROUTINE,
            severities=(SeverityRule("loss", 1),),
            human_judgement_required=False,
        )


def test_artistry_candidate_remains_human_review_even_with_high_machine_confidence():
    proposal = evaluate_deduction_candidate(
        policy(),
        candidate(
            rule_id="fixture.artistry.criterion",
            severity="criterion-loss",
            confidence=1000,
            quality=1000,
            capabilities=frozenset(),
        ),
    )
    assert proposal.state is ProposalState.NEEDS_REVIEW
    assert proposal.rule_applicability is RuleApplicability.CONDITIONAL
    assert proposal.human_judgement_required is True
    assert "qualitative-human-judgement-required" in proposal.review_reasons


def test_candidate_severity_must_be_allowed_by_pinned_rule():
    with pytest.raises(DeductionError, match="severity is not allowed"):
        evaluate_deduction_candidate(policy(), candidate(severity="invented-large"))


def test_human_accept_or_change_requires_explicit_rule_allowed_severity():
    proposal = evaluate_deduction_candidate(policy(), candidate())
    ledger = DeductionDecisionLedger(policy(), (proposal,))
    with pytest.raises(DeductionError, match="severity is not allowed"):
        ledger.append(decision(proposal, severity="invented"))

    with pytest.raises(DeductionError, match="requires explicit selected severity"):
        DeductionDecision(
            decision_id="missing-severity",
            proposal_digest=proposal.digest,
            candidate_id=proposal.candidate_id,
            action=DecisionAction.ACCEPT,
            author_id="reviewer-a",
            created_at=T0,
            reason="No implicit severity allowed",
        )


def test_decision_history_is_append_only_and_cannot_fork():
    proposal = evaluate_deduction_candidate(policy(), candidate())
    first = decision(proposal, created_at=T0)
    revised = decision(
        proposal,
        decision_id="decision-2",
        action=DecisionAction.CHANGE,
        severity="medium",
        created_at=T0 + timedelta(minutes=1),
        supersedes=first.decision_id,
    )
    ledger = DeductionDecisionLedger(policy(), (proposal,), (first, revised))
    assert ledger.current(proposal.candidate_id) == revised

    with pytest.raises(DeductionError, match="cannot fork"):
        ledger.append(
            decision(
                proposal,
                decision_id="decision-3",
                action=DecisionAction.REJECT,
                severity=None,
                created_at=T0 + timedelta(minutes=2),
                supersedes=first.decision_id,
            )
        )


def test_only_current_human_decisions_create_accepted_deduction_total():
    p_accept = evaluate_deduction_candidate(policy(), candidate("accept"))
    p_reject = evaluate_deduction_candidate(policy(), candidate("reject", severity="medium"))
    p_open = evaluate_deduction_candidate(policy(), candidate("open"))
    p_escalate = evaluate_deduction_candidate(policy(), candidate("escalate"))
    proposals = (p_open, p_escalate, p_reject, p_accept)
    decisions = DeductionDecisionLedger(policy(), proposals)
    decisions.append(decision(p_accept, decision_id="d-accept", severity="small"))
    decisions.append(
        decision(
            p_reject,
            decision_id="d-reject",
            action=DecisionAction.REJECT,
            severity=None,
        )
    )
    decisions.append(
        decision(
            p_escalate,
            decision_id="d-escalate",
            action=DecisionAction.ESCALATE,
            severity=None,
        )
    )

    result = build_deduction_ledger(policy(), tuple(reversed(proposals)), decisions)
    assert len(result.accepted) == 1
    assert isinstance(result.accepted[0], AcceptedDeductionEntry)
    assert result.accepted[0].candidate_id == "accept"
    assert result.accepted[0].deduction_units == 1
    assert result.accepted_deduction_units == 1
    assert result.rejected_candidate_ids == ("reject",)
    assert result.unresolved_candidate_ids == ("open",)
    assert result.escalated_candidate_ids == ("escalate",)
    assert result.fully_resolved is False


def test_revised_decision_uses_new_selected_severity_not_original_model_suggestion():
    proposal = evaluate_deduction_candidate(policy(), candidate(severity="small"))
    first = decision(proposal, decision_id="d1", severity="small", created_at=T0)
    changed = decision(
        proposal,
        decision_id="d2",
        action=DecisionAction.CHANGE,
        severity="medium",
        created_at=T0 + timedelta(seconds=1),
        supersedes="d1",
    )
    decisions = DeductionDecisionLedger(policy(), (proposal,), (first, changed))
    result = build_deduction_ledger(policy(), (proposal,), decisions)
    assert result.accepted[0].severity_id == "medium"
    assert result.accepted[0].deduction_units == 3


def test_policy_and_ledger_digest_are_stable_and_rulepack_bound():
    proposal = evaluate_deduction_candidate(policy(), candidate())
    decisions = DeductionDecisionLedger(policy(), (proposal,))
    decisions.append(decision(proposal))
    first = build_deduction_ledger(policy(), (proposal,), decisions)
    second = build_deduction_ledger(policy(), (proposal,), decisions)
    assert first.normalized_json() == second.normalized_json()
    assert first.digest == second.digest
    assert first.rulepack_digest == RULEPACK_DIGEST
