from datetime import UTC, datetime

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import (
    AnalysisJob,
    Event,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
    Routine,
)


@pytest.mark.django_db
def test_analysis_inbox_filters_searches_and_prioritizes_review(client):
    user = User.objects.create_user("operator")
    organization = Organization.objects.create(name="Inbox Club", slug="inbox")
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.OPERATOR)
    level = Level.objects.create(organization=organization, name="Senior")
    event = Event.objects.create(
        organization=organization,
        name="Summer Cup",
        kind=Event.Kind.COMPETITION,
        starts_at=datetime.now(UTC),
    )
    jobs = []
    for number, (name, apparatus, state) in enumerate(
        (
            ("Ada", Routine.Apparatus.BEAM, AnalysisJob.State.QUEUED),
            ("Bella", Routine.Apparatus.FLOOR, AnalysisJob.State.NEEDS_REVIEW),
        ),
        start=1,
    ):
        gymnast = Gymnast.objects.create(
            organization=organization,
            level=level,
            display_name=name,
            license_number=f"LIC-{number}",
        )
        routine = Routine.objects.create(
            organization=organization,
            event=event,
            gymnast=gymnast,
            apparatus=apparatus,
            rulepack_id="wag@1",
        )
        media = MediaAsset.objects.create(
            organization=organization,
            gymnast=gymnast,
            routine=routine,
            kind=MediaAsset.Kind.COMPETITION,
            state=MediaAsset.State.STORED,
            recorded_at=datetime.now(UTC),
        )
        jobs.append(
            AnalysisJob.objects.create(
                organization=organization,
                media=media,
                state=state,
                scope="routine",
                rulepack_id="wag@1",
                model_profile="baseline",
            )
        )
    client.force_login(user)
    page = client.get(reverse("analyses"))
    assert page.status_code == 200
    assert next(iter(page.context["jobs"])).id == jobs[1].id
    filtered = client.get(reverse("analyses"), {"apparatus": "BB", "q": "LIC-1"})
    body = filtered.content.decode()
    assert "Ada" in body and "Bella" not in body


@pytest.mark.django_db
def test_analysis_inbox_remains_organization_scoped(client):
    user = User.objects.create_user("viewer")
    own = Organization.objects.create(name="Own", slug="own")
    other = Organization.objects.create(name="Other", slug="other")
    Membership.objects.create(user=user, organization=own, role=Membership.Role.VIEWER)
    level = Level.objects.create(organization=other, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=other, level=level, display_name="Hidden", license_number="SECRET"
    )
    media = MediaAsset.objects.create(
        organization=other,
        gymnast=gymnast,
        kind=MediaAsset.Kind.DRILL,
        recorded_at=datetime.now(UTC),
    )
    AnalysisJob.objects.create(
        organization=other,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="drill",
        rulepack_id="wag@1",
        model_profile="baseline",
    )
    client.force_login(user)
    assert "Hidden" not in client.get(reverse("analyses")).content.decode()
