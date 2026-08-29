from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.review_workflow import (
    ReviewAction,
    ReviewArtifactKind,
    ReviewArtifactRef,
    ReviewDecision,
    ReviewDecisionLedger,
    ReviewFilter,
    ReviewItem,
    ReviewReason,
    ReviewState,
    ReviewWorkflowError,
    build_review_evidence_export,
    filter_review_inbox,
    validate_bulk_action,
)

T0 = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def ref(kind: ReviewArtifactKind, seed: str) -> ReviewArtifactRef:
    return ReviewArtifactRef(
        artifact_id=f"{kind.value}:{seed}",
        artifact_digest=(seed if seed in "123456789abcdef" else "1") * 64,
        kind=kind,
        schema=f"{kind.value}-v1",
    )


def item(
    review_id: str,
    *,
    reason: ReviewReason = ReviewReason.LOW_CONFIDENCE,
    apparatus: Apparatus = Apparatus.BB,
    material: bool = True,
    confidence: int | None = 400,
    assignee: str | None = None,
    age_minutes: int = 10,
) -> ReviewItem:
    kwargs = {}
    if reason is ReviewReason.SCORE_DISCREPANCY:
        kwargs["deterministic_result"] = ref(ReviewArtifactKind.DETERMINISTIC_RULE_RESULT, "2")
        kwargs["official_result"] = ref(ReviewArtifactKind.OFFICIAL_RESULT, "3")
    if reason is ReviewReason.RULE_MISMATCH:
        kwargs["rule_sources"] = (ref(ReviewArtifactKind.RULE_SOURCE, "4"),)
    return ReviewItem(
        review_id=review_id,
        organization_id="org-1",
        analysis_id="analysis-1",
        analysis_revision_id="revision-1",
        analysis_revision_digest="a" * 64,
        apparatus=apparatus,
        reason=reason,
        material=material,
        created_at=T0 - timedelta(minutes=age_minutes),
        confidence_milli=confidence,
        evidence=(ref(ReviewArtifactKind.EVIDENCE, "1"),),
        ai_proposal=ref(ReviewArtifactKind.AI_PROPOSAL, "5"),
        assignee_id=assignee,
        **kwargs,
    )


def decision(
    item_: ReviewItem,
    decision_id: str,
    action: ReviewAction,
    *,
    when: datetime,
    qualification: str | None = "qualified-reviewer:wags",
    supersedes: str | None = None,
) -> ReviewDecision:
    revised = (
        ref(ReviewArtifactKind.HUMAN_REVISION, "6")
        if action is ReviewAction.REVISE
        else None
    )
    return ReviewDecision(
        decision_id=decision_id,
        review_id=item_.review_id,
        review_item_digest=item_.digest,
        action=action,
        reviewer_id="reviewer-1",
        reviewer_qualification_ref=qualification,
        reason_code=f"reason-{action.value}",
        notes=f"Reviewed fixture: {action.value}",
        created_at=when,
        revised_artifact=revised,
        supersedes_decision_id=supersedes,
    )


def test_score_discrepancy_requires_official_and_deterministic_artifacts():
    with pytest.raises(ReviewWorkflowError, match="official result"):
        ReviewItem(
            review_id="review-bad",
            organization_id="org-1",
            analysis_id="analysis-1",
            analysis_revision_id="revision-1",
            analysis_revision_digest="a" * 64,
            apparatus=Apparatus.BB,
            reason=ReviewReason.SCORE_DISCREPANCY,
            material=True,
            created_at=T0,
            confidence_milli=500,
            evidence=(ref(ReviewArtifactKind.EVIDENCE, "1"),),
            deterministic_result=ref(ReviewArtifactKind.DETERMINISTIC_RULE_RESULT, "2"),
        )


def test_rule_mismatch_requires_rule_source():
    with pytest.raises(ReviewWorkflowError, match="rule source"):
        ReviewItem(
            review_id="review-rule",
            organization_id="org-1",
            analysis_id="analysis-1",
            analysis_revision_id="revision-1",
            analysis_revision_digest="a" * 64,
            apparatus=Apparatus.UB,
            reason=ReviewReason.RULE_MISMATCH,
            material=True,
            created_at=T0,
            confidence_milli=700,
            evidence=(ref(ReviewArtifactKind.EVIDENCE, "1"),),
        )


def test_material_decision_requires_qualified_reviewer_reference():
    review = item("review-1", material=True)
    ledger = ReviewDecisionLedger(review)
    with pytest.raises(ReviewWorkflowError, match="requires reviewer qualification"):
        ledger.append(
            decision(
                review,
                "decision-1",
                ReviewAction.ACCEPT,
                when=T0,
                qualification=None,
            )
        )


def test_nonmaterial_decision_may_be_resolved_without_domain_qualification():
    review = item("review-nonmaterial", material=False)
    ledger = ReviewDecisionLedger(review)
    accepted = decision(
        review,
        "decision-1",
        ReviewAction.ACCEPT,
        when=T0,
        qualification=None,
    )
    ledger.append(accepted)
    assert ledger.current == accepted
    assert ledger.state is ReviewState.RESOLVED


def test_review_decision_history_is_append_only_and_new_decision_must_supersede_current():
    review = item("review-history")
    first = decision(review, "decision-1", ReviewAction.ESCALATE, when=T0)
    second = decision(
        review,
        "decision-2",
        ReviewAction.REJECT,
        when=T0 + timedelta(minutes=1),
        supersedes="decision-1",
    )
    ledger = ReviewDecisionLedger(review, (first, second))
    assert ledger.state is ReviewState.RESOLVED
    assert ledger.current == second

    with pytest.raises(ReviewWorkflowError, match="explicitly supersede current"):
        ledger.append(
            decision(
                review,
                "decision-3",
                ReviewAction.ACCEPT,
                when=T0 + timedelta(minutes=2),
                supersedes="decision-1",
            )
        )


def test_revise_requires_immutable_human_revision_artifact_and_other_actions_cannot_carry_it():
    review = item("review-revise")
    with pytest.raises(ReviewWorkflowError, match="requires revised artifact"):
        ReviewDecision(
            decision_id="decision-bad",
            review_id=review.review_id,
            review_item_digest=review.digest,
            action=ReviewAction.REVISE,
            reviewer_id="reviewer-1",
            reviewer_qualification_ref="qualified-reviewer:wags",
            reason_code="revise",
            notes="Revision required",
            created_at=T0,
        )

    revised = decision(review, "decision-revise", ReviewAction.REVISE, when=T0)
    assert revised.revised_artifact.kind is ReviewArtifactKind.HUMAN_REVISION


def test_material_review_items_cannot_be_bulk_accepted_rejected_or_revised():
    material = item("review-material", material=True)
    nonmaterial = item("review-small", material=False)
    for action in (ReviewAction.ACCEPT, ReviewAction.REJECT, ReviewAction.REVISE):
        with pytest.raises(ReviewWorkflowError):
            validate_bulk_action((material, nonmaterial), action)


def test_bulk_escalation_is_allowed_but_not_material_bulk_resolution():
    ids = validate_bulk_action(
        (item("review-2", material=True), item("review-1", material=False)),
        ReviewAction.ESCALATE,
    )
    assert ids == ("review-1", "review-2")


def test_inbox_filters_reason_confidence_age_apparatus_and_assignee_deterministically():
    items = (
        item(
            "r1",
            reason=ReviewReason.LOW_CONFIDENCE,
            apparatus=Apparatus.BB,
            confidence=200,
            assignee="reviewer-1",
            age_minutes=60,
        ),
        item(
            "r2",
            reason=ReviewReason.POOR_QUALITY,
            apparatus=Apparatus.BB,
            confidence=100,
            assignee=None,
            age_minutes=120,
        ),
        item(
            "r3",
            reason=ReviewReason.LOW_CONFIDENCE,
            apparatus=Apparatus.FX,
            confidence=300,
            assignee="reviewer-1",
            age_minutes=90,
        ),
        item(
            "r4",
            reason=ReviewReason.LOW_CONFIDENCE,
            apparatus=Apparatus.BB,
            confidence=800,
            assignee="reviewer-1",
            age_minutes=180,
        ),
    )
    filtered = filter_review_inbox(
        items,
        filter=ReviewFilter(
            reasons=frozenset({ReviewReason.LOW_CONFIDENCE}),
            apparatuses=frozenset({Apparatus.BB}),
            assignee_id="reviewer-1",
            confidence_at_most_milli=500,
            minimum_age_seconds=30 * 60,
            material_only=True,
        ),
        now=T0,
    )
    assert [entry.review_id for entry in filtered] == ["r1"]


def test_unassigned_filter_is_separate_from_named_assignee_filter():
    items = (
        item("r1", assignee=None),
        item("r2", assignee="reviewer-1"),
    )
    unassigned = filter_review_inbox(
        items,
        filter=ReviewFilter(unassigned_only=True),
        now=T0,
    )
    assert [entry.review_id for entry in unassigned] == ["r1"]

    with pytest.raises(ReviewWorkflowError, match="cannot filter"):
        ReviewFilter(assignee_id="reviewer-1", unassigned_only=True)


def test_review_evidence_export_binds_item_decisions_evidence_rules_and_analysis_revision():
    review = item("review-export", reason=ReviewReason.RULE_MISMATCH)
    first = decision(review, "decision-1", ReviewAction.REVISE, when=T0)
    second = decision(
        review,
        "decision-2",
        ReviewAction.ACCEPT,
        when=T0 + timedelta(minutes=1),
        supersedes="decision-1",
    )
    ledger = ReviewDecisionLedger(review, (first, second))
    export = build_review_evidence_export(
        review,
        ledger,
        created_at=T0 + timedelta(minutes=2),
    )
    assert export.review_item_digest == review.digest
    assert export.decision_digests == (first.digest, second.digest)
    assert export.evidence_digests == (review.evidence[0].artifact_digest,)
    assert export.rule_source_digests == (review.rule_sources[0].artifact_digest,)
    assert export.analysis_revision_digest == review.analysis_revision_digest
    assert len(export.digest) == 64
