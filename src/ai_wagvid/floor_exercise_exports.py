"""Canonical public projection for floor-exercise evidence."""

from __future__ import annotations

from typing import Any

from .floor_exercise import FloorExerciseBundle


def floor_exercise_payload(bundle: FloorExerciseBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.floor-exercise-analysis.v1",
        "analysis_id": bundle.analysis_id,
        "routine_id": bundle.routine_id,
        "apparatus": bundle.apparatus.value,
        "source_media_sha256": bundle.source_media_sha256,
        "timing": {
            "start_ms": bundle.timing.start_ms,
            "end_ms": bundle.timing.end_ms,
            "duration_ms": bundle.timing.duration_ms,
            "source": bundle.timing.source.value,
            "timeline_digest": bundle.timing.timeline_digest,
            "confidence_milli": bundle.timing.confidence_milli,
            "evidence_digests": [item.digest for item in bundle.timing.evidence],
            "limitations": list(bundle.timing.limitations),
            "timing_digest": bundle.timing.digest,
        },
        "geometry": {
            "state": bundle.geometry.state.value,
            "floor_polygon_digest": bundle.geometry.floor_polygon_digest,
            "reason": bundle.geometry.reason,
        },
        "model_bundle_digest": bundle.model_bundle_digest,
        "perception_bundle_digest": bundle.perception_bundle_digest,
        "created_at": bundle.created_at.isoformat(),
        "limitations": list(bundle.limitations),
        "bundle_digest": bundle.digest,
        "intervals": [
            {
                "interval_id": item.interval_id,
                "kind": item.kind.value,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "confidence_milli": item.confidence_milli,
                "temporal_candidate_digest": item.temporal_candidate_digest,
                "family": item.family,
                "element_id": item.element_id,
                "accepted": item.accepted,
                "limitations": list(item.limitations),
                "evidence_digests": [ref.digest for ref in item.evidence],
                "interval_digest": item.digest,
            }
            for item in bundle.intervals
        ],
        "observations": [
            {
                "observation_id": item.observation_id,
                "kind": item.kind.value,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "value": item.value,
                "confidence_milli": item.confidence_milli,
                "floor_polygon_digest": item.floor_polygon_digest,
                "criterion_id": item.criterion_id,
                "limitations": list(item.limitations),
                "evidence_digests": [ref.digest for ref in item.evidence],
                "observation_digest": item.digest,
            }
            for item in bundle.observations
        ],
        "connections": [
            {
                "connection_id": item.connection_id,
                "first_interval_id": item.first_interval_id,
                "second_interval_id": item.second_interval_id,
                "gap_ms": item.gap_ms,
                "evidence_observation_ids": list(item.evidence_observation_ids),
                "state": item.state,
                "confidence_milli": item.confidence_milli,
            }
            for item in bundle.connections
        ],
    }
