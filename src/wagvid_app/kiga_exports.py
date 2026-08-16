"""Privacy-minimized KIGA competition-video export."""

from __future__ import annotations

from decimal import Decimal

from .models import AnalysisResult, Routine, ScoreComparisonReview


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def export_kiga_routine(routine: Routine) -> dict:
    event = routine.event
    references = list(routine.external_media_references.order_by("external_media_id"))
    if not references:
        raise ValueError("KIGA export requires at least one authorized external media reference")
    official = routine.official_versions.first()
    if not official:
        raise ValueError("KIGA export requires a versioned official result")
    job = routine.media.order_by("-recorded_at").first()
    analysis = None
    if job:
        analysis_job = job.analysis_jobs.select_related("result").order_by("-revision").first()
        result = getattr(analysis_job, "result", None) if analysis_job else None
        if result and result.state in {
            AnalysisResult.State.HUMAN_CONFIRMED,
            AnalysisResult.State.PANEL_CONFIRMED,
            AnalysisResult.State.FROZEN,
        }:
            analysis = {
                "analysis_id": str(analysis_job.id),
                "state": result.state.upper().replace("-", "_"),
                "ai_frozen_at": (result.frozen_at or result.updated_at).isoformat(),
                "official_result_revealed_at": routine.official_frozen_at.isoformat()
                if routine.official_frozen_at
                else None,
                "difference": (
                    _number(result.proposed_final_score - routine.official_final_score)
                    if result.proposed_final_score is not None
                    and routine.official_final_score is not None
                    else None
                ),
            }
    review = (
        ScoreComparisonReview.objects.filter(result__analysis_job__media__routine=routine)
        .select_related("reviewer")
        .first()
    )
    review_map = {
        ScoreComparisonReview.Decision.OFFICIAL_CONFIRMED: "official_confirmed",
        ScoreComparisonReview.Decision.AI_DISCREPANCY_SUPPORTED: "ai_supported",
        ScoreComparisonReview.Decision.CORRECTED_LABELS: "both_partly_wrong",
        ScoreComparisonReview.Decision.INCONCLUSIVE: "unresolved",
    }
    adjudication = (
        {
            "status": review_map[review.decision],
            "reviewer_id": str(review.reviewer_id),
            "reviewed_at": review.created_at.isoformat(),
            "reason_codes": [],
            "notes": review.notes or None,
            "appeal_reference": None,
        }
        if review
        else {"status": "pending"}
    )
    adjudicated = bool(review and review.decision != ScoreComparisonReview.Decision.INCONCLUSIVE)
    training_allowed = all(item.training_allowed for item in references)
    eligible = adjudicated and training_allowed
    return {
        "schema": "ai.wagvid.competition-video.v1",
        "record_id": f"wagvid:{routine.id}:{official.result_version}",
        "created_at": routine.updated_at.isoformat(),
        "competition": {
            "external_id": event.external_id,
            "provider": event.external_source or "KIGA",
            "name": event.name,
            "start_date": event.starts_at.date().isoformat(),
            "end_date": event.ends_at.date().isoformat() if event.ends_at else None,
            "timezone": event.timezone_name,
            "venue": event.venue or None,
            "city": event.city or None,
            "country_code": event.country_code or None,
            "organizer": event.organizer or None,
            "federation": event.federation or None,
            "competition_level": event.competition_level or None,
            "rule_profile": event.rule_profile or None,
        },
        "routine": {
            "external_id": routine.external_id,
            "athlete_external_id": routine.gymnast.kiga_id,
            "team_external_id": None,
            "apparatus": routine.apparatus,
            "round": routine.round_name or None,
            "rotation": routine.rotation,
            "start_order": routine.start_order,
            "performed_at": routine.performed_at.isoformat(),
            "age_category": routine.age_category or None,
            "competition_category": routine.category or None,
        },
        "media": [
            {
                "media_id": item.external_media_id,
                "camera_id": item.camera_id or None,
                "view": item.view or None,
                "download_uri": item.download_uri,
                "sha256": item.sha256,
                "captured_at": item.captured_at.isoformat(),
                "content_type": item.content_type,
                "size_bytes": item.size_bytes,
                "duration_ms": item.duration_ms,
            }
            for item in references
        ],
        "official_result": {
            "source": official.source,
            "status": official.status,
            "captured_at": official.source_captured_at.isoformat(),
            "result_version": official.result_version,
            "scores": {
                "d": _number(official.d_score),
                "e": _number(official.e_score),
                "artistry": _number(official.artistry),
                "neutral": _number(official.neutral),
                "final": _number(official.final_score),
            },
        },
        "analysis_link": analysis,
        "adjudication": adjudication,
        "learning": {
            "eligible": eligible,
            "label_tier": "expert_adjudicated" if eligible else "excluded",
            "exclusion_reasons": [] if eligible else ["not-expert-adjudicated"],
            "dataset_version": None,
        },
        "rights": {
            "download_allowed": all(item.download_allowed for item in references),
            "analysis_allowed": all(item.analysis_allowed for item in references),
            "training_allowed": training_allowed,
            "retention_until": min(
                (item.retention_until for item in references if item.retention_until), default=None
            ).isoformat()
            if any(item.retention_until for item in references)
            else None,
            "consent_reference": references[0].consent_reference or None,
            "access_policy": references[0].access_policy or None,
        },
    }
