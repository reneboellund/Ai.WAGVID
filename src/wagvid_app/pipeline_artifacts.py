"""Schema-bound persistence for immutable analysis-pipeline artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from .models import AnalysisDeliverable, AnalysisJob
from .reporting import _require_reporter, _validate, canonical_digest


@dataclass(frozen=True)
class ArtifactDefinition:
    kind: str
    schema_file: str
    apparatus: str | None = None


ARTIFACT_DEFINITIONS = {
    "ai.wagvid.temporal-recognition.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.TEMPORAL_RECOGNITION,
        "temporal-recognition-v1.schema.json",
    ),
    "ai.wagvid.dscore-ledger.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.DSCORE_LEDGER,
        "dscore-ledger-v1.schema.json",
    ),
    "ai.wagvid.deduction-ledger.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.DEDUCTION_LEDGER,
        "deduction-ledger-v1.schema.json",
    ),
    "ai.wagvid.vault-analysis.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.APPARATUS_ANALYSIS,
        "vault-analysis-v1.schema.json",
        "VT",
    ),
    "ai.wagvid.uneven-bars-topology.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.APPARATUS_ANALYSIS,
        "uneven-bars-topology-v1.schema.json",
        "UB",
    ),
    "ai.wagvid.balance-beam-analysis.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.APPARATUS_ANALYSIS,
        "balance-beam-analysis-v1.schema.json",
        "BB",
    ),
    "ai.wagvid.floor-exercise-analysis.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.APPARATUS_ANALYSIS,
        "floor-exercise-analysis-v1.schema.json",
        "FX",
    ),
    "ai.wagvid.release-validation.v1": ArtifactDefinition(
        AnalysisDeliverable.Kind.VALIDATION_MANIFEST,
        "release-validation-v1.schema.json",
    ),
}


@transaction.atomic
def publish_pipeline_artifact(
    *,
    job: AnalysisJob,
    actor,
    payload: dict,
    upstream_digests: tuple[str, ...] = (),
) -> AnalysisDeliverable:
    """Validate, provenance-bind and persist one idempotent pipeline artifact."""

    job = (
        AnalysisJob.objects.select_for_update()
        .select_related("organization", "media__gymnast", "media__routine__event")
        .get(pk=job.pk)
    )
    _require_reporter(actor, job.organization)
    if not isinstance(payload, dict):
        raise TypeError("pipeline artifact payload must be a JSON object")
    schema_id = payload.get("schema")
    definition = ARTIFACT_DEFINITIONS.get(schema_id)
    if definition is None:
        raise ValueError("unsupported pipeline artifact schema")
    _validate(payload, definition.schema_file)

    routine = job.media.routine
    payload_apparatus = payload.get("apparatus")
    if definition.apparatus and payload_apparatus != definition.apparatus:
        raise ValueError("artifact apparatus does not match its schema")
    if routine and payload_apparatus and routine.apparatus != payload_apparatus:
        raise ValueError("artifact apparatus does not match the analysis routine")

    normalized_upstream = tuple(sorted(set(upstream_digests)))
    if any(len(value) != 64 or value.lower() != value for value in normalized_upstream):
        raise ValueError("upstream digests must be lowercase SHA-256 values")
    payload_digest = canonical_digest(payload)
    existing = AnalysisDeliverable.objects.filter(
        organization=job.organization,
        analysis_job=job,
        schema_id=schema_id,
        payload_digest=payload_digest,
    ).first()
    if existing:
        if existing.provenance.get("upstream_digests", []) != list(normalized_upstream):
            raise ValueError("identical payload is already bound to different upstream artifacts")
        return existing

    revision = job.deliverables.filter(kind=definition.kind).count() + 1
    deliverable = AnalysisDeliverable.objects.create(
        organization=job.organization,
        kind=definition.kind,
        schema_id=schema_id,
        analysis_job=job,
        gymnast=job.media.gymnast,
        event=routine.event if routine else None,
        revision=revision,
        payload=payload,
        payload_digest=payload_digest,
        provenance={
            "media_sha256": job.media.sha256,
            "rulepack_id": job.rulepack_id,
            "model_profile": job.model_profile,
            "upstream_digests": list(normalized_upstream),
        },
        generated_by=actor,
    )
    job.organization.audit_events.create(
        actor=actor,
        action="analysis.pipeline-artifact-published",
        object_type="analysis-deliverable",
        object_id=str(deliverable.id),
        metadata={
            "analysis_job_id": str(job.id),
            "schema": schema_id,
            "digest": payload_digest,
            "upstream_digests": list(normalized_upstream),
        },
    )
    return deliverable
