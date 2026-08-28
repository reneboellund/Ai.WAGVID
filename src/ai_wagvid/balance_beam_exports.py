"""Canonical public projection for balance-beam evidence."""

from __future__ import annotations

from typing import Any

from .balance_beam import BalanceBeamBundle


def balance_beam_payload(bundle: BalanceBeamBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.balance-beam-analysis.v1",
        "analysis_id": bundle.analysis_id,
        "routine_id": bundle.routine_id,
        "apparatus": bundle.apparatus.value,
        "source_media_sha256": bundle.source_media_sha256,
        "geometry": {
            "state": bundle.geometry.state.value,
            "geometry_digest": bundle.geometry.geometry_digest,
            "reason": bundle.geometry.reason,
        },
        "model_bundle_digest": bundle.model_bundle_digest,
        "perception_bundle_digest": bundle.perception_bundle_digest,
        "created_at": bundle.created_at.isoformat(),
        "limitations": list(bundle.limitations),
        "bundle_digest": bundle.digest,
        "observations": [
            {
                "observation_id": item.observation_id,
                "kind": item.kind.value,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "value": item.value,
                "confidence_milli": item.confidence_milli,
                "geometry_digest": item.geometry_digest,
                "criterion_id": item.criterion_id,
                "limitations": list(item.limitations),
                "evidence_digests": [ref.digest for ref in item.evidence],
                "observation_digest": item.digest,
            }
            for item in bundle.observations
        ],
        "elements": [
            {
                "segment_id": item.segment_id,
                "temporal_candidate_digest": item.temporal_candidate_digest,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "family": item.family,
                "element_id": item.element_id,
                "accepted": item.accepted,
            }
            for item in bundle.elements
        ],
        "series": [
            {
                "series_id": item.series_id,
                "segment_ids": list(item.segment_ids),
                "state": item.state.value,
                "gap_ms": list(item.gap_ms),
                "evidence_observation_ids": list(item.evidence_observation_ids),
                "confidence_milli": item.confidence_milli,
            }
            for item in bundle.series
        ],
        "artistry_decisions": [
            {
                "decision_id": item.decision_id,
                "criterion_id": item.criterion_id,
                "observation_digests": list(item.observation_digests),
                "reviewer_id": item.reviewer_id,
                "reviewer_qualification_ref": item.reviewer_qualification_ref,
                "accepted": item.accepted,
                "reason_code": item.reason_code,
                "notes": item.notes,
                "decided_at": item.decided_at.isoformat(),
                "decision_digest": item.digest,
            }
            for item in bundle.artistry_decisions
        ],
    }
