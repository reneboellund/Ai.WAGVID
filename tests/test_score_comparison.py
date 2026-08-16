from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from ai_wagvid.score_comparison import ScoreLine, compare_scores
from wagvid_app.models import (
    AnalysisJob,
    AnalysisResult,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
    ScoreComparisonReview,
)
from wagvid_app.operations import InvalidStateTransition, record_score_comparison_review


def test_score_comparison_flags_threshold_and_missing_evidence():
    result = compare_scores(
        ScoreLine(Decimal("5.200"), Decimal("8.000"), Decimal(0), Decimal("13.200")),
        ScoreLine(Decimal("5.200"), Decimal("7.899"), None, Decimal("13.099")),
    )
    assert result.needs_review
    assert result.missing_fields == ("neutral",)
    assert {item.field for item in result.differences if item.exceeds_threshold} == {
        "e_score",
        "final_score",
    }


def review_fixture(role=Membership.Role.REVIEWER):
    user = User.objects.create_user(f"user-{role}")
    organization = Organization.objects.create(name="Review Club", slug=f"review-{role}")
    Membership.objects.create(user=user, organization=organization, role=role)
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(
        organization=organization,
        level=level,
        display_name="Review Gymnast",
        license_number="REV-1",
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.ROUTINE,
        state=MediaAsset.State.STORED,
        recorded_at=datetime.now(UTC),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="routine",
        rulepack_id="wag@1",
        model_profile="baseline",
    )
    result = AnalysisResult.objects.create(
        analysis_job=job, state=AnalysisResult.State.NEEDS_REVIEW
    )
    return user, organization, job, result


@pytest.mark.django_db
def test_corrected_labels_require_complete_scores_and_finalize_review():
    user, organization, job, result = review_fixture()
    with pytest.raises(ValueError, match="require"):
        record_score_comparison_review(
            result_id=result.id,
            reviewer=user,
            decision=ScoreComparisonReview.Decision.CORRECTED_LABELS,
            accepted_scores={"final_score": Decimal("13.000")},
        )
    review = record_score_comparison_review(
        result_id=result.id,
        reviewer=user,
        decision=ScoreComparisonReview.Decision.CORRECTED_LABELS,
        accepted_scores={
            "d_score": Decimal("5.000"),
            "e_score": Decimal("8.100"),
            "neutral": Decimal("0.100"),
            "final_score": Decimal("13.000"),
        },
        notes="Frame review completed",
    )
    job.refresh_from_db()
    result.refresh_from_db()
    assert job.state == AnalysisJob.State.COMPLETED
    assert result.state == AnalysisResult.State.HUMAN_CONFIRMED
    assert review.accepted_final_score == Decimal("13.000")
    assert organization.audit_events.filter(
        action="analysis.score-comparison-reviewed"
    ).exists()
    with pytest.raises(ValueError, match="append-only"):
        review.delete()


@pytest.mark.django_db
def test_score_review_requires_role_and_pending_state():
    user, _, job, result = review_fixture(role=Membership.Role.COACH)
    with pytest.raises(PermissionError):
        record_score_comparison_review(
            result_id=result.id,
            reviewer=user,
            decision=ScoreComparisonReview.Decision.INCONCLUSIVE,
        )
    job.state = AnalysisJob.State.COMPLETED
    job.save()
    with pytest.raises(InvalidStateTransition):
        record_score_comparison_review(
            result_id=result.id,
            reviewer=user,
            decision=ScoreComparisonReview.Decision.INCONCLUSIVE,
        )
