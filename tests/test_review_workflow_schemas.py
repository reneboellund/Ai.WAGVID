from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.domain import Apparatus
from ai_wagvid.review_exports import review_decision_payload, review_item_payload
from ai_wagvid.review_workflow import (
    ReviewAction,
    ReviewArtifactKind,
    ReviewArtifactRef,
    ReviewDecision,
    ReviewItem,
    ReviewReason,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
ITEM_SCHEMA = load_schema(ROOT / "schemas" / "review-item-v1.schema.json")
DECISION_SCHEMA = load_schema(ROOT / "schemas" / "review-decision-v1.schema.json")
T0 = datetime(2026, 8, 17, 19, 30, tzinfo=UTC)


def ref(kind: ReviewArtifactKind, seed: str):
    return ReviewArtifactRef(
        artifact_id=f"{kind.value}:{seed}",
        artifact_digest=seed * 64,
        kind=kind,
        schema=f"{kind.value}-v1",
    )


def discrepancy_item():
    return ReviewItem(
        review_id="review-1",
        organization_id="org-1",
        analysis_id="analysis-1",
        analysis_revision_id="revision-1",
        analysis_revision_digest="a" * 64,
        apparatus=Apparatus.BB,
        reason=ReviewReason.SCORE_DISCREPANCY,
        material=True,
        created_at=T0,
        confidence_milli=700,
        evidence=(ref(ReviewArtifactKind.EVIDENCE, "1"),),
        ai_proposal=ref(ReviewArtifactKind.AI_PROPOSAL, "2"),
        deterministic_result=ref(ReviewArtifactKind.DETERMINISTIC_RULE_RESULT, "3"),
        official_result=ref(ReviewArtifactKind.OFFICIAL_RESULT, "4"),
        rule_sources=(ref(ReviewArtifactKind.RULE_SOURCE, "5"),),
    )


def test_review_item_serializer_validates_public_schema():
    payload = review_item_payload(discrepancy_item())
    errors = list(
        Draft202012Validator(
            ITEM_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []


def test_score_discrepancy_schema_rejects_missing_official_result():
    payload = review_item_payload(discrepancy_item())
    payload["official_result"] = None
    assert list(Draft202012Validator(ITEM_SCHEMA).iter_errors(payload))


def test_review_decision_serializer_validates_public_schema():
    item = discrepancy_item()
    decision = ReviewDecision(
        decision_id="decision-1",
        review_id=item.review_id,
        review_item_digest=item.digest,
        action=ReviewAction.REVISE,
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        reason_code="identity-corrected",
        notes="Reviewed evidence and revised candidate identity",
        created_at=T0,
        revised_artifact=ref(ReviewArtifactKind.HUMAN_REVISION, "6"),
    )
    payload = review_decision_payload(decision)
    errors = list(
        Draft202012Validator(
            DECISION_SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == []


def test_revise_schema_rejects_missing_human_revision_artifact():
    item = discrepancy_item()
    decision = ReviewDecision(
        decision_id="decision-1",
        review_id=item.review_id,
        review_item_digest=item.digest,
        action=ReviewAction.REVISE,
        reviewer_id="reviewer-1",
        reviewer_qualification_ref="qualified-reviewer:wags",
        reason_code="identity-corrected",
        notes="Reviewed evidence and revised candidate identity",
        created_at=T0,
        revised_artifact=ref(ReviewArtifactKind.HUMAN_REVISION, "6"),
    )
    payload = review_decision_payload(decision)
    payload["revised_artifact"] = None
    assert list(Draft202012Validator(DECISION_SCHEMA).iter_errors(payload))
