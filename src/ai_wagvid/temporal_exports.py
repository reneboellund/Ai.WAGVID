"""Canonical public projection for temporal recognition bundles.

The projection is intentionally pre-scoring: exact source intervals, evidence-backed observations,
ranked element alternatives, explicit unknown/OOD mass and model/perception provenance are public;
D/E/final scores and official-result context have no representation here.
"""

from __future__ import annotations

from typing import Any

from .temporal_recognition import TemporalRecognitionBundle


def temporal_recognition_payload(bundle: TemporalRecognitionBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.temporal-recognition.v1",
        "bundle_id": bundle.bundle_id,
        "routine_id": bundle.routine_id,
        "apparatus": bundle.apparatus.value,
        "model_bundle_digest": bundle.model_bundle_digest,
        "perception_bundle_digest": bundle.perception_bundle_digest,
        "created_at": bundle.created_at.isoformat(),
        "limitations": list(bundle.limitations),
        "bundle_digest": bundle.digest,
        "candidates": [
            {
                "segment_id": candidate.segment_id,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "views": [
                    {
                        "media_sha256": view.media_sha256,
                        "camera_id": view.camera_id,
                        "start_ms": view.start_ms,
                        "end_ms": view.end_ms,
                        "evidence_digest": view.evidence_digest,
                        "view_digest": view.digest,
                    }
                    for view in candidate.views
                ],
                "observations": [
                    {
                        "observation_id": observation.observation_id,
                        "evidence_digest": observation.evidence_digest,
                        "attribute": observation.attribute,
                        "value": observation.value,
                        "confidence_milli": observation.confidence_milli,
                        "observation_digest": observation.digest,
                    }
                    for observation in candidate.observations
                ],
                "probability": {
                    "alternatives": [
                        {
                            "element_id": alternative.element_id,
                            "family": alternative.family,
                            "probability_milli": alternative.probability_milli,
                            "distinguishing_observation_ids": list(
                                alternative.distinguishing_observation_ids
                            ),
                        }
                        for alternative in candidate.probability.alternatives
                    ],
                    "unknown_ood_milli": candidate.probability.unknown_ood_milli,
                    "other_known_milli": candidate.probability.other_known_milli,
                },
                "model_bundle_digest": candidate.model_bundle_digest,
                "model_config_digest": candidate.model_config_digest,
                "perception_bundle_digest": candidate.perception_bundle_digest,
                "sequence_context_digest": candidate.sequence_context_digest,
                "created_at": candidate.created_at.isoformat(),
                "limitations": list(candidate.limitations),
                "candidate_digest": candidate.digest,
            }
            for candidate in bundle.candidates
        ],
    }
