from datetime import UTC, datetime
from fractions import Fraction

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai_wagvid.media_timeline import FrameTimestamp, build_timeline
from wagvid_app.annotation_operations import create_annotation_revision, revise_annotation
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


@pytest.mark.django_db
def test_review_revision_is_append_only_and_export_contains_only_latest_accepted(monkeypatch, client):
    _, user, job, timeline = setup_job()
    monkeypatch.setattr("wagvid_app.annotation_operations.load_media_timeline", lambda media: timeline)
    first = create_annotation_revision(
        job=job, actor=user, kind="element", label="Element X", start_frame_index=1,
        end_frame_index=3, state=EvidenceAnnotationRevision.State.SUBMITTED, timeline=timeline,
    )
    accepted = revise_annotation(
        annotation=first, actor=user, state=EvidenceAnnotationRevision.State.ACCEPTED,
        label="Element Y", comment="Reviewed against canonical frames",
    )
    assert accepted.parent_id == first.id
    assert accepted.revision == 2
    assert first.state == EvidenceAnnotationRevision.State.SUBMITTED
    client.force_login(user)
    response = client.get(reverse("annotation-export", args=[job.id]))
    payload = response.json()
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert len(payload["labels"]) == 1
    assert payload["labels"][0]["label"] == "Element Y"
    assert payload["labels"][0]["time_base"] == [1, 1000]
    assert "display_name" not in response.content.decode()


@pytest.mark.django_db
def test_annotator_cannot_self_accept_and_old_revision_cannot_be_revised(monkeypatch):
    _, user, job, timeline = setup_job(Membership.Role.ANNOTATOR)
    monkeypatch.setattr("wagvid_app.annotation_operations.load_media_timeline", lambda media: timeline)
    first = create_annotation_revision(
        job=job, actor=user, kind="phase", label="Flight", start_frame_index=0,
        end_frame_index=2, timeline=timeline,
    )
    with pytest.raises(PermissionError, match="reviewer role"):
        revise_annotation(
            annotation=first, actor=user, state=EvidenceAnnotationRevision.State.ACCEPTED,
            comment="self approval",
        )
    second = revise_annotation(
        annotation=first, actor=user, state=EvidenceAnnotationRevision.State.SUBMITTED,
        comment="submit",
    )
    assert second.revision == 2
    with pytest.raises(ValueError, match="latest"):
        revise_annotation(
            annotation=first, actor=user, state=EvidenceAnnotationRevision.State.SUBMITTED,
            comment="stale",
        )
