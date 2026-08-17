"""Canonical JSON projections for the review inbox and append-only human decisions."""

from __future__ import annotations

from typing import Any

from .review_workflow import ReviewDecision, ReviewEvidenceExport, ReviewItem


def review_item_payload(item: ReviewItem) -> dict[str, Any]:
    def artifact(ref):
        if ref is None:
            return None
        return {
            "artifact_id": ref.artifact_id,
            "artifact_digest": ref.artifact_digest,
            "kind": ref.kind.value,
            "schema": ref.schema,
        }

    return {
        "schema": "ai.wagvid.review-item.v1",
        "review_id": item.review_id,
        "organization_id": item.organization_id,
        "analysis_id": item.analysis_id,
        "analysis_revision_id": item.analysis_revision_id,
        "analysis_revision_digest": item.analysis_revision_digest,
        "apparatus": item.apparatus.value,
        "reason": item.reason.value,
        "material": item.material,
        "created_at": item.created_at.isoformat(),
        "confidence_milli": item.confidence_milli,
        "assignee_id": item.assignee_id,
        "evidence": [artifact(ref) for ref in item.evidence],
        "ai_proposal": artifact(item.ai_proposal),
        "deterministic_result": artifact(item.deterministic_result),
        "official_result": artifact(item.official_result),
        "rule_sources": [artifact(ref) for ref in item.rule_sources],
        "review_item_digest": item.digest,
    }


def review_decision_payload(decision: ReviewDecision) -> dict[str, Any]:
    revised = decision.revised_artifact
    return {
        "schema": "ai.wagvid.review-decision.v1",
        "decision_id": decision.decision_id,
        "review_id": decision.review_id,
        "review_item_digest": decision.review_item_digest,
        "action": decision.action.value,
        "reviewer_id": decision.reviewer_id,
        "reviewer_qualification_ref": decision.reviewer_qualification_ref,
        "reason_code": decision.reason_code,
        "notes": decision.notes,
        "created_at": decision.created_at.isoformat(),
        "revised_artifact": (
            {
                "artifact_id": revised.artifact_id,
                "artifact_digest": revised.artifact_digest,
                "kind": revised.kind.value,
                "schema": revised.schema,
            }
            if revised
            else None
        ),
        "supersedes_decision_id": decision.supersedes_decision_id,
        "decision_digest": decision.digest,
    }


def review_evidence_export_payload(export: ReviewEvidenceExport) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.review-evidence-export.v1",
        "export_id": export.export_id,
        "review_item_digest": export.review_item_digest,
        "decision_digests": list(export.decision_digests),
        "evidence_digests": list(export.evidence_digests),
        "rule_source_digests": list(export.rule_source_digests),
        "analysis_revision_digest": export.analysis_revision_digest,
        "created_at": export.created_at.isoformat(),
        "export_digest": export.digest,
    }
