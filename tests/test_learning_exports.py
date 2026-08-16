from decimal import Decimal

import pytest
from django.urls import reverse

from tests.test_review_workspace import make_review_case
from wagvid_app.learning_exports import reviewed_score_labels
from wagvid_app.models import Membership, ScoreComparisonReview
from wagvid_app.operations import record_score_comparison_review


@pytest.mark.django_db
def test_corrected_review_is_exported_with_provenance_and_no_reviewer_identity_feature():
    user, organization, _, candidate = make_review_case()
    review = record_score_comparison_review(
        result_id=candidate.result_id,
        reviewer=user,
        decision=ScoreComparisonReview.Decision.CORRECTED_LABELS,
        accepted_scores={
            "d_score": Decimal("4.200"),
            "e_score": Decimal("7.800"),
            "neutral": Decimal("0.000"),
            "final_score": Decimal("12.000"),
        },
    )
    labels = reviewed_score_labels(organization)
    assert labels[0]["label_source"] == "human-corrected"
    assert labels[0]["scores"]["final_score"] == "12.000"
    assert labels[0]["review"]["id"] == str(review.id)
    assert "reviewer_name" not in labels[0]["review"]


@pytest.mark.django_db
def test_inconclusive_review_is_not_exported_as_ground_truth():
    user, organization, _, candidate = make_review_case()
    record_score_comparison_review(
        result_id=candidate.result_id,
        reviewer=user,
        decision=ScoreComparisonReview.Decision.INCONCLUSIVE,
    )
    assert reviewed_score_labels(organization) == []


@pytest.mark.django_db
def test_research_export_is_role_scoped_and_audited(client):
    user, organization, _, candidate = make_review_case(role=Membership.Role.RESEARCHER)
    ScoreComparisonReview.objects.create(
        result_id=candidate.result_id,
        reviewer=user,
        decision=ScoreComparisonReview.Decision.CORRECTED_LABELS,
        accepted_d_score=Decimal("4.200"),
        accepted_e_score=Decimal("7.800"),
        accepted_neutral=Decimal("0.000"),
        accepted_final_score=Decimal("12.000"),
    )
    client.force_login(user)
    response = client.get(reverse("reviewed-labels-export"))
    assert response.status_code == 200
    assert response.json()["schema"] == "ai.wagvid.reviewed-score-label-set.v1"
    assert response["Content-Disposition"].endswith("wagvid-reviewed-labels.json\"")
    assert organization.audit_events.filter(action="research.reviewed-labels-exported").exists()


@pytest.mark.django_db
def test_coach_cannot_export_learning_labels(client):
    user, _, _, _ = make_review_case(role=Membership.Role.COACH)
    client.force_login(user)
    assert client.get(reverse("reviewed-labels-export")).status_code == 403
