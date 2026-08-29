"""Immutable canonical-frame annotation operations."""

from __future__ import annotations

from django.db import transaction

from .media_timeline_store import load_media_timeline
from .models import AnalysisJob, EvidenceAnnotationRevision, Membership


def _require_annotator(actor, organization) -> None:
    allowed = [
        Membership.Role.SYSTEM_ADMIN,
        Membership.Role.ORGANIZATION_ADMIN,
        Membership.Role.REVIEWER,
        Membership.Role.DOMAIN_REVIEWER,
        Membership.Role.ANNOTATOR,
        Membership.Role.RESEARCHER,
    ]
    if not actor.wagvid_memberships.filter(organization=organization, active=True, role__in=allowed).exists():
        raise PermissionError("annotation role is required")


@transaction.atomic
def create_annotation_revision(
    *,
    job: AnalysisJob,
    actor,
    kind: str,
    label: str,
    start_frame_index: int,
    end_frame_index: int,
    state: str = EvidenceAnnotationRevision.State.DRAFT,
    parent: EvidenceAnnotationRevision | None = None,
    calibration: dict | None = None,
    attributes: dict | None = None,
    rule_reference: str = "",
    comment: str = "",
    timeline=None,
) -> EvidenceAnnotationRevision:
    job = AnalysisJob.objects.select_for_update().select_related("organization", "media").get(pk=job.pk)
    _require_annotator(actor, job.organization)
    if kind not in EvidenceAnnotationRevision.Kind.values or state not in EvidenceAnnotationRevision.State.values:
        raise ValueError("annotation kind/state is invalid")
    if not label.strip():
        raise ValueError("annotation label is required")
    canonical = timeline or load_media_timeline(job.media)
    if canonical.source_sha256 != job.media.sha256:
        raise ValueError("canonical timeline belongs to another source")
    if start_frame_index < 0 or end_frame_index < start_frame_index or end_frame_index >= len(canonical.frames):
        raise ValueError("annotation frame interval is invalid")
    if parent and (parent.organization_id != job.organization_id or parent.analysis_job_id != job.id):
        raise ValueError("annotation parent belongs to another job or organization")
    root = (parent.parent or parent) if parent else None
    revision = 1 if root is None else root.revisions.count() + 2
    start = canonical.frames[start_frame_index]
    end = canonical.frames[end_frame_index]
    value = EvidenceAnnotationRevision.objects.create(
        organization=job.organization,
        analysis_job=job,
        parent=root,
        revision=revision,
        kind=kind,
        label=label.strip(),
        state=state,
        source_sha256=job.media.sha256,
        timeline_digest=canonical.digest,
        stream_index=canonical.stream_index,
        start_frame_index=start_frame_index,
        end_frame_index=end_frame_index,
        start_timestamp_ticks=start.best_effort_timestamp,
        end_timestamp_ticks=end.best_effort_timestamp,
        time_base_numerator=canonical.time_base.numerator,
        time_base_denominator=canonical.time_base.denominator,
        calibration=calibration or {},
        attributes=attributes or {},
        rule_reference=rule_reference.strip(),
        comment=comment.strip(),
        created_by=actor,
    )
    job.organization.audit_events.create(
        actor=actor,
        action="evidence.annotation-revision-created",
        object_type="evidence-annotation",
        object_id=str(value.id),
        metadata={"analysis_job_id": str(job.id), "revision": revision, "timeline_digest": canonical.digest},
    )
    return value
