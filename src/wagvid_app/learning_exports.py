"""Human-reviewed score labels suitable for controlled research export."""

from __future__ import annotations

from .models import Organization, ScoreComparisonReview


def reviewed_score_labels(organization: Organization) -> list[dict]:
    reviews = (
        ScoreComparisonReview.objects.filter(result__analysis_job__organization=organization)
        .select_related(
            "reviewer",
            "result__analysis_job__media__routine",
            "result__analysis_job__media",
        )
        .order_by("created_at", "id")
    )
    labels = []
    for review in reviews:
        routine = review.result.analysis_job.media.routine
        if review.decision == ScoreComparisonReview.Decision.CORRECTED_LABELS:
            scores = {
                "d_score": review.accepted_d_score,
                "e_score": review.accepted_e_score,
                "neutral": review.accepted_neutral,
                "final_score": review.accepted_final_score,
            }
            label_source = "human-corrected"
        elif (
            review.decision == ScoreComparisonReview.Decision.OFFICIAL_CONFIRMED and routine
        ):
            scores = {
                "d_score": routine.official_d_score,
                "e_score": routine.official_e_score,
                "neutral": routine.official_neutral,
                "final_score": routine.official_final_score,
            }
            label_source = "official-human-confirmed"
        else:
            continue
        if any(value is None for value in scores.values()):
            continue
        labels.append(
            {
                "schema": "ai.wagvid.reviewed-score-label.v1",
                "analysis_result_id": str(review.result_id),
                "media_id": str(review.result.analysis_job.media_id),
                "media_sha256": review.result.analysis_job.media.sha256 or None,
                "routine_id": str(routine.id) if routine else None,
                "apparatus": routine.apparatus if routine else None,
                "rulepack_id": review.result.analysis_job.rulepack_id,
                "label_source": label_source,
                "scores": {key: str(value) for key, value in scores.items()},
                "review": {
                    "id": str(review.id),
                    "reviewer_id": str(review.reviewer_id),
                    "decision": review.decision,
                    "created_at": review.created_at.isoformat(),
                },
            }
        )
    return labels
