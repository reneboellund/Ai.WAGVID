"""Canonical public projection for the VT evidence contract."""

from __future__ import annotations

from typing import Any

from .vault import VaultAnalysisBundle


def vault_analysis_payload(bundle: VaultAnalysisBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.vault-analysis.v1",
        "analysis_id": bundle.analysis_id,
        "routine_id": bundle.routine_id,
        "apparatus": bundle.apparatus.value,
        "source_media_sha256": bundle.source_media_sha256,
        "model_bundle_digest": bundle.model_bundle_digest,
        "perception_bundle_digest": bundle.perception_bundle_digest,
        "created_at": bundle.created_at.isoformat(),
        "limitations": list(bundle.limitations),
        "analysis_digest": bundle.digest,
        "corridor_boundary_capability": {
            "state": bundle.corridor_boundary_capability.state.value,
            "calibration_digest": bundle.corridor_boundary_capability.calibration_digest,
            "reason": bundle.corridor_boundary_capability.reason,
        },
        "phases": [
            {
                "phase": item.phase.value,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "confidence_milli": item.confidence_milli,
                "evidence": [
                    {
                        "evidence_id": ref.evidence_id,
                        "evidence_digest": ref.evidence_digest,
                        "start_ms": ref.start_ms,
                        "end_ms": ref.end_ms,
                        "camera_id": ref.camera_id,
                        "ref_digest": ref.digest,
                    }
                    for ref in item.evidence
                ],
                "phase_digest": item.digest,
            }
            for item in bundle.phases
        ],
        "observations": [
            {
                "observation_id": item.observation_id,
                "kind": item.kind.value,
                "phase": item.phase.value,
                "value": item.value,
                "confidence_milli": item.confidence_milli,
                "calibration_digest": item.calibration_digest,
                "limitations": list(item.limitations),
                "evidence": [
                    {
                        "evidence_id": ref.evidence_id,
                        "evidence_digest": ref.evidence_digest,
                        "start_ms": ref.start_ms,
                        "end_ms": ref.end_ms,
                        "camera_id": ref.camera_id,
                        "ref_digest": ref.digest,
                    }
                    for ref in item.evidence
                ],
                "observation_digest": item.digest,
            }
            for item in bundle.observations
        ],
        "identity": {
            "alternatives": [
                {
                    "element_id": item.element_id,
                    "family": item.family,
                    "probability_milli": item.probability_milli,
                    "evidence_observation_ids": list(item.evidence_observation_ids),
                }
                for item in bundle.identity.alternatives
            ],
            "unknown_ood_milli": bundle.identity.unknown_ood_milli,
            "other_known_milli": bundle.identity.other_known_milli,
        },
    }
