from datetime import UTC, datetime
from fractions import Fraction

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai_wagvid.media_timeline import FrameTimestamp, build_timeline
from wagvid_app.annotation_operations import create_annotation_revision
from wagvid_app.models import (
    AnalysisJob,
    EvidenceAnnotationRevision,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
)


def setup_job(role=Membership.Role.REVIEWER):
    organization = Organization.objects.create(name="Annotation Club", slug=f"annotation-{role}")
    user = User.objects.create_user(f"annotation-{role}", password="secret")
    Membership.objects.create(user=user, organization=organization, role=role)
    level = Level.objects.create(organization=organization, name="Level")
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Ada", license_number=f"A-{role}", level=level
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
        object_key="annotation/source.mp4",
        sha256="a" * 64,
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="drill",
        rulepack_id="wag-test@1",
        model_profile="baseline",
    )
    timeline = build_timeline(
        source_sha256=media.sha256,
        time_base=Fraction(1, 1000),
        frames=tuple(FrameTimestamp(i, i * 40, i * 40, i * 40, 40, i == 0) for i in range(5)),
    )
    return organization, user, job, timeline


@pytest.mark.django_db
def test_annotation_revision_preserves_canonical_frame_evidence_and_is_immutable():
    organization, user, job, timeline = setup_job()
    annotation = create_annotation_revision(
        job=job,
        actor=user,
        kind=EvidenceAnnotationRevision.Kind.LANDING,
        label="Large landing step",
        start_frame_index=1,
        end_frame_index=3,
        state=EvidenceAnnotationRevision.State.SUBMITTED,
        timeline=timeline,
    )
    assert (annotation.start_timestamp_ticks, annotation.end_timestamp_ticks) == (40, 120)
    assert annotation.timeline_digest == timeline.digest
    assert annotation.source_sha256 == job.media.sha256
    assert organization.audit_events.filter(action="evidence.annotation-revision-created").exists()
    annotation.label = "changed"
    with pytest.raises(ValueError, match="immutable"):
        annotation.save()
    with pytest.raises(ValueError, match="immutable"):
        annotation.delete()


@pytest.mark.django_db
def test_annotation_rejects_invalid_range_and_unauthorized_role():
    _, user, job, timeline = setup_job(Membership.Role.VIEWER)
    with pytest.raises(PermissionError, match="annotation role"):
        create_annotation_revision(
            job=job, actor=user, kind="landing", label="x", start_frame_index=0,
            end_frame_index=1, timeline=timeline,
        )
    Membership.objects.filter(user=user).update(role=Membership.Role.REVIEWER)
    with pytest.raises(ValueError, match="frame interval"):
        create_annotation_revision(
            job=job, actor=user, kind="landing", label="x", start_frame_index=4,
            end_frame_index=5, timeline=timeline,
        )


@pytest.mark.django_db
def test_review_page_exposes_annotation_controls_and_history(client):
    _, user, job, timeline = setup_job()
    create_annotation_revision(
        job=job, actor=user, kind="element", label="Element X", start_frame_index=0,
        end_frame_index=2, timeline=timeline,
    )
    client.force_login(user)
    response = client.get(reverse("analysis-review", args=[job.id]))
    body = response.content.decode()
    assert response.status_code == 200
    assert "Canonical annotationer" in body
    assert "Element X" in body
    assert reverse("annotation-create", args=[job.id]) in body
    assert "data-mark-start" in body
