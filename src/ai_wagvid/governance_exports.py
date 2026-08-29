"""Canonical audit/export projections for cross-cutting governance records.

These serializers expose references/digests and policy decisions, never plaintext operational
secrets. They are suitable as append-only audit payloads or internal governance exports.
"""

from __future__ import annotations

import json
from typing import Any

from .data_governance import (
    DatasetRightsRecord,
    DeletionDecision,
    FrozenConfigSnapshot,
    ProductionDecisionProvenance,
)


def dataset_rights_payload(record: DatasetRightsRecord) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.dataset-rights.v1",
        "record_id": record.record_id,
        "source_reference": record.source_reference,
        "source_digest": record.source_digest,
        "rights_reference": record.rights_reference,
        "rights_digest": record.rights_digest,
        "permissions": sorted(item.value for item in record.permissions),
        "retention_class": record.retention_class,
        "valid_from": record.valid_from.isoformat(),
        "valid_until": record.valid_until.isoformat() if record.valid_until else None,
        "lifecycle": record.lifecycle.value,
        "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
        "record_digest": record.digest,
    }


def deletion_decision_payload(decision: DeletionDecision) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.deletion-decision.v1",
        "media_id": decision.media_id,
        "request_digest": decision.request_digest,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "disposition": decision.disposition.value,
        "blockers": list(decision.blockers),
        "earliest_physical_delete_at": (
            decision.earliest_physical_delete_at.isoformat()
            if decision.earliest_physical_delete_at
            else None
        ),
    }


def frozen_config_payload(snapshot: FrozenConfigSnapshot) -> dict[str, Any]:
    """Serialize only sanitized public config plus secret references, never secret values."""
    return {
        "schema": "ai.wagvid.frozen-config.v1",
        "snapshot_id": snapshot.snapshot_id,
        "organization_id": snapshot.organization_id,
        "schema_version": snapshot.schema_version,
        "config_digest": snapshot.config_digest,
        "secret_references": list(snapshot.secret_references),
        "created_at": snapshot.created_at.isoformat(),
        "public_config": json.loads(snapshot.public_config_json),
    }


def production_decision_payload(decision: ProductionDecisionProvenance) -> dict[str, Any]:
    return {
        "schema": "ai.wagvid.production-decision-provenance.v1",
        "decision_id": decision.decision_id,
        "organization_id": decision.organization_id,
        "object_ref": decision.object_ref,
        "semantic_layer": decision.semantic_layer.value,
        "state": decision.state.value,
        "material": decision.material,
        "authority_ref": decision.authority_ref,
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "evidence_digest": item.evidence_digest,
                "canonical_source_sha256": item.canonical_source_sha256,
                "kind": item.kind.value,
                "represented_as_original": item.represented_as_original,
                "evidence_provenance_digest": item.digest,
            }
            for item in decision.evidence
        ],
        "rulepack_digest": decision.rulepack_digest,
        "model_bundle_digest": decision.model_bundle_digest,
        "software_digest": decision.software_digest,
        "config_digest": decision.config_digest,
        "calibration_digest": decision.calibration_digest,
        "created_at": decision.created_at.isoformat(),
        "limitations": list(decision.limitations),
        "supersedes_decision_id": decision.supersedes_decision_id,
        "decision_digest": decision.digest,
    }
