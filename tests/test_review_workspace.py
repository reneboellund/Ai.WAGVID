from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import (
    AnalysisJob,
    AnalysisResult,
    DeductionCandidate,
    Event,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
    ReviewDecision,
    Routine,
)


def make_review_case(role=Membership.Role.REVIEWER):
    user = User.objects.create_user("reviewer", password="secret")
    organization = Organization.objects.create(name="Club", slug="club")
    Membership.objects.create(user=user, organization=organization, role=role)
    level = Level.objects.create(organization=organization, name="Trin 5")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Ada",
        license_number="DK-10",
    )
    event = Event.objects.create(
        organization=organization,
        name="Test Cup",
        kind=Event.Kind.COMPETITION,
        starts_at=datetime.now(UTC),
    )
    routine = Routine.objects.create(
        organization=organization,
        event=event,
        gymnast=gymnast,
        apparatus=Routine.Apparatus.BEAM,
        rulepack_id="wag-test@1",
        official_d_score=Decimal("4.200"),
        official_e_score=Decimal("7.900"),
        official_final_score=Decimal("12.100"),
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        routine=routine,
        kind=MediaAsset.Kind.COMPETITION,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="routine",
        rulepack_id="wag-test@1",
        model_profile="baseline",
    )
    result = AnalysisResult.objects.create(
        analysis_job=job,
        state=AnalysisResult.State.NEEDS_REVIEW,
        proposed_d_score=Decimal("4.200"),
        proposed_e_score=Decimal("7.800"),
        proposed_final_score=Decimal("12.000"),
    )
    candidate = DeductionCandidate.objects.create(
        result=result,
        criterion="Landing step",
        rule_reference="E-LANDING-STEP",
        start_ms=51000,
        end_ms=52500,
        proposed_amount=Decimal("0.100"),
        model_confidence=Decimal("0.9200"),
        evidence={"clip": "evidence/landing.mp4", "source": "original"},
    )
    return user, organization, job, candidate


@pytest.mark.django_db
def test_reviewer_sees_official_ai_and_evidence_then_decides(client):
    user, organization, job, candidate = make_review_case()
    client.force_login(user)
    page = client.get(reverse("analysis-review", args=[job.id]))
    body = page.content.decode()
    assert page.status_code == 200
    assert "Test Cup" in body
    assert "12,100" in body
    assert "12,000" in body
    assert "Landing step" in body

    response = client.post(
        reverse("review-decision", args=[candidate.id]),
        {"decision": ReviewDecision.Decision.OFFICIAL_ERROR, "notes": "Clear step."},
    )
    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == DeductionCandidate.ReviewState.ACCEPTED
    decision = candidate.decisions.get()
    assert decision.reviewer == user
    assert organization.audit_events.filter(action="deduction.reviewed").exists()


@pytest.mark.django_db
def test_non_reviewer_cannot_submit_decision(client):
    user, _, _, candidate = make_review_case(role=Membership.Role.COACH)
    client.force_login(user)
    response = client.post(
        reverse("review-decision", args=[candidate.id]),
        {"decision": ReviewDecision.Decision.ACCEPT_AI},
    )
    assert response.status_code == 403
    assert candidate.decisions.count() == 0


@pytest.mark.django_db
def test_mag_gymnast_and_apparatus_are_explicit_dimensions():
    organization = Organization.objects.create(name="MAG Club", slug="mag-club")
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=organization,
        display_name="Magnus",
        license_number="MAG-1",
        discipline=Gymnast.Discipline.MAG,
        level=level,
    )
    event = Event.objects.create(
        organization=organization,
        name="MAG Test",
        kind=Event.Kind.TEST,
        starts_at=datetime.now(UTC),
    )
    routine = Routine.objects.create(
        organization=organization,
        event=event,
        gymnast=gymnast,
        apparatus=Routine.Apparatus.STILL_RINGS,
        rulepack_id="mag-test@1",
    )
    assert routine.apparatus == "SR"
    assert routine.gymnast.discipline == "MAG"
