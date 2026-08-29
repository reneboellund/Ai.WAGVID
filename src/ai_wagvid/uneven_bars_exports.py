"""Canonical public projection for uneven-bars contact topology."""

from __future__ import annotations

from typing import Any

from .uneven_bars import UnevenBarsTopologyBundle


def uneven_bars_payload(bundle: UnevenBarsTopologyBundle) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.uneven-bars-topology.v1",
        "analysis_id": bundle.analysis_id,
        "routine_id": bundle.routine_id,
        "apparatus": bundle.apparatus.value,
        "source_media_sha256": bundle.source_media_sha256,
        "geometry_digest": bundle.geometry_digest,
        "model_bundle_digest": bundle.model_bundle_digest,
        "perception_bundle_digest": bundle.perception_bundle_digest,
        "created_at": bundle.created_at.isoformat(),
        "limitations": list(bundle.limitations),
        "bundle_digest": bundle.digest,
        "contacts": [
            {
                "contact_id": item.contact_id,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "state": item.state.value,
                "bar": item.bar.value,
                "confidence_milli": item.confidence_milli,
                "geometry_digest": item.geometry_digest,
                "limitations": list(item.limitations),
                "evidence_digests": [ref.digest for ref in item.evidence],
                "contact_digest": item.digest,
            }
            for item in bundle.contacts
        ],
        "events": [
            {
                "event_id": item.event_id,
                "kind": item.kind.value,
                "at_ms": item.at_ms,
                "from_bar": item.from_bar.value,
                "to_bar": item.to_bar.value,
                "confidence_milli": item.confidence_milli,
                "geometry_digest": item.geometry_digest,
                "limitations": list(item.limitations),
                "evidence_digests": [ref.digest for ref in item.evidence],
                "event_digest": item.digest,
            }
            for item in bundle.events
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
        "continuity": [
            {
                "continuity_id": item.continuity_id,
                "first_segment_id": item.first_segment_id,
                "second_segment_id": item.second_segment_id,
                "gap_ms": item.gap_ms,
                "evidence_event_ids": list(item.evidence_event_ids),
                "state": item.state,
                "confidence_milli": item.confidence_milli,
            }
            for item in bundle.continuity
        ],
    }
