import hashlib
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import AnalysisJob, Gymnast, Level, MediaAsset, Membership, Organization


@pytest.mark.django_db
def test_review_workspace_exposes_signed_source_loader_for_verified_media(client):
    organization = Organization.objects.create(name="Evidence Club", slug="evidence-club")
    user = User.objects.create_user("evidence-reviewer", password="secret")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.REVIEWER)
    level = Level.objects.create(organization=organization, name="Youth")
    gymnast = Gymnast.objects.create(
        organization=organization,
        display_name="Evidence Gymnast",
        license_number="EV-1",
        level=level,
    )
    digest = hashlib.sha256(b"verified-video").hexdigest()
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        state=MediaAsset.State.STORED,
        object_key="evidence/original.mp4",
        sha256=digest,
        original_filename="original.mp4",
        content_type="video/mp4",
        size_bytes=14,
        recorded_at=datetime.now(UTC),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="drill",
        rulepack_id="wag-test@1",
        model_profile="baseline",
    )
    client.force_login(user)
    response = client.get(reverse("analysis-review", args=[job.id]))
    body = response.content.decode()
    assert response.status_code == 200
    assert "Autoriseret source-video" in body
    assert reverse("media-object-grant", args=[media.id]) in body
    assert "data-evidence-video" in body
    assert "opfinder ikke frame-numre" in body
