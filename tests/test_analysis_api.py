import json
from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import AnalysisJob, Gymnast, Level, MediaAsset, Membership, Organization


def setup_media(*, state=MediaAsset.State.STORED):
    user = User.objects.create_user("analyst", password="secret")
    organization = Organization.objects.create(name="Club", slug="club")
    Membership.objects.create(
        user=user, organization=organization, role=Membership.Role.RESEARCHER
    )
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=organization,
        display_name="Ada",
        license_number="A-1",
        level=level,
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        state=state,
        kind=MediaAsset.Kind.ROUTINE,
        recorded_at=datetime.now(UTC),
    )
    return user, organization, media


def request_payload(media, request_id="request-1"):
    return {
        "media_id": str(media.id),
        "client_request_id": request_id,
        "scope": "routine",
        "rulepack_id": "wag-test@1",
        "model_profile": "baseline",
    }


@pytest.mark.django_db
def test_analysis_api_queues_idempotently_and_returns_status(client):
    user, organization, media = setup_media()
    client.force_login(user)
    response = client.post(
        reverse("api-analyses-create"),
        json.dumps(request_payload(media)),
        content_type="application/json",
    )
    assert response.status_code == 201
    analysis_id = response.json()["analysis_id"]
    repeated = client.post(
        reverse("api-analyses-create"),
        json.dumps(request_payload(media)),
        content_type="application/json",
    )
    assert repeated.status_code == 200
    assert repeated.json()["analysis_id"] == analysis_id
    assert AnalysisJob.objects.count() == 1
    assert organization.audit_events.filter(action="analysis.queued").count() == 1
    detail = client.get(reverse("api-analysis-detail", args=[analysis_id]))
    assert detail.status_code == 200
    assert detail.json()["state"] == AnalysisJob.State.QUEUED


@pytest.mark.django_db
def test_analysis_api_rejects_changed_idempotency_request_and_unstored_media(client):
    user, organization, media = setup_media()
    client.force_login(user)
    payload = request_payload(media)
    assert client.post(
        reverse("api-analyses-create"), json.dumps(payload), content_type="application/json"
    ).status_code == 201
    payload["scope"] = "single-skill"
    assert client.post(
        reverse("api-analyses-create"), json.dumps(payload), content_type="application/json"
    ).status_code == 400

    pending = MediaAsset.objects.create(
        organization=organization,
        gymnast=media.gymnast,
        state=MediaAsset.State.UPLOADING,
        kind=MediaAsset.Kind.ROUTINE,
        recorded_at=datetime.now(UTC),
    )
    rejected = client.post(
        reverse("api-analyses-create"),
        json.dumps(request_payload(pending, "request-2")),
        content_type="application/json",
    )
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_analysis_api_is_organization_scoped_and_requires_login(client):
    user, _, media = setup_media()
    assert client.post(
        reverse("api-analyses-create"),
        json.dumps(request_payload(media)),
        content_type="application/json",
    ).status_code == 302
    other = Organization.objects.create(name="Other", slug="other")
    Membership.objects.create(user=user, organization=other, role=Membership.Role.RESEARCHER)
    client.force_login(user)
    response = client.post(
        reverse("api-analyses-create"),
        json.dumps(request_payload(media)),
        content_type="application/json",
        HTTP_X_WAGVID_ORGANIZATION="other",
    )
    assert response.status_code == 400
