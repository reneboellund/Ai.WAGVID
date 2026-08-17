"""Authoritative safe factories for the KIGA integration contracts.

Callers should use this module rather than instantiating low-level integration dataclasses from
untrusted mappings. It adds strict JSON finiteness, immutable revision construction and one
canonical row representation shared by JSON and future Parquet writers.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Iterable, Mapping

from .kiga_integration import (
    AnalysisReviewState,
    BatchExportFormat,
    KigaAnalysisExportRevision,
    KigaBatchExportManifest,
    KigaIntegrationError,
    PublicAnalysisArtifact,
    PublicSchemaVersion,
    StableKigaIdentity,
    TrainingRightsAssertion,
    build_batch_manifest,
    export_revision_id,
    public_analysis_artifact,
)


def build_public_analysis_artifact(
    payload: Mapping[str, Any],
    *,
    schema: PublicSchemaVersion,
    review_state: AnalysisReviewState,
) -> PublicAnalysisArtifact:
    """Build public analysis JSON with RFC-compatible finite numeric values only."""
    _require_json_finite(payload)
    # `public_analysis_artifact` performs the recursive raw-model-field safety check and
    # review/disclosure mapping. `allow_nan=False` here guarantees canonical strict JSON.
    json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return public_analysis_artifact(payload, schema=schema, review_state=review_state)


def build_export_revision(
    *,
    identity: StableKigaIdentity,
    analysis_id: str,
    analysis_revision_id: str,
    analysis_revision_digest: str,
    artifact: PublicAnalysisArtifact,
    rulepack_digest: str,
    model_bundle_digest: str,
    software_digest: str,
    training_rights: TrainingRightsAssertion,
    created_at: datetime,
    supersedes_export_id: str | None = None,
) -> KigaAnalysisExportRevision:
    """Create deterministic immutable export identity from analysis revision + public payload."""
    export_id = export_revision_id(
        identity=identity,
        analysis_revision_digest=analysis_revision_digest,
        artifact=artifact,
    )
    return KigaAnalysisExportRevision(
        export_id=export_id,
        identity=identity,
        analysis_id=analysis_id,
        analysis_revision_id=analysis_revision_id,
        analysis_revision_digest=analysis_revision_digest,
        artifact=artifact,
        rulepack_digest=rulepack_digest,
        model_bundle_digest=model_bundle_digest,
        software_digest=software_digest,
        training_rights=training_rights,
        created_at=created_at,
        supersedes_export_id=supersedes_export_id,
    )


def canonical_batch_rows(
    exports: Iterable[KigaAnalysisExportRevision],
) -> tuple[dict[str, Any], ...]:
    """Return one stable flat-ish row contract for JSON and Parquet serialization.

    `analysis_json` is a canonical JSON string so nested analysis semantics remain governed by
    the negotiated analysis schema instead of being flattened differently by each file format.
    """
    items = tuple(exports)
    rows = []
    for export in items:
        envelope = export.public_envelope()
        analysis = envelope.pop("analysis")
        rows.append(
            {
                **envelope,
                "export_digest": export.digest,
                "analysis_json": json.dumps(
                    analysis,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            }
        )
    rows.sort(key=lambda item: (item["competition_external_id"], item["routine_external_id"], item["export_id"]))
    return tuple(rows)


def serialize_batch_json(
    exports: Iterable[KigaAnalysisExportRevision],
    *,
    created_at: datetime,
) -> tuple[KigaBatchExportManifest, bytes]:
    """Serialize canonical rows to deterministic JSON and return the matching manifest."""
    items = tuple(exports)
    manifest = build_batch_manifest(
        items,
        format=BatchExportFormat.JSON,
        created_at=created_at,
    )
    rows = canonical_batch_rows(items)
    payload = {
        "schema": "ai.wagvid.kiga-batch-export.v1",
        "batch_export_id": manifest.batch_export_id,
        "analysis_schema": manifest.schema.identifier,
        "format": manifest.format.value,
        "export_digests": list(manifest.export_digests),
        "rows": list(rows),
    }
    return manifest, json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def parquet_rows_and_manifest(
    exports: Iterable[KigaAnalysisExportRevision],
    *,
    created_at: datetime,
) -> tuple[KigaBatchExportManifest, tuple[dict[str, Any], ...]]:
    """Return the exact rows an optional Parquet adapter must write.

    Core does not require PyArrow. Deployment/export workers may serialize these rows with a
    pinned Parquet implementation; semantic equivalence to JSON is maintained by using the same
    canonical row contract and export digests.
    """
    items = tuple(exports)
    manifest = build_batch_manifest(
        items,
        format=BatchExportFormat.PARQUET,
        created_at=created_at,
    )
    return manifest, canonical_batch_rows(items)


def batch_bytes_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_json_finite(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _require_json_finite(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _require_json_finite(child, path=f"{path}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise KigaIntegrationError(f"non-finite number is forbidden in public JSON at {path}")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return
    raise KigaIntegrationError(
        f"unsupported value type in public JSON at {path}: {type(value).__name__}"
    )
