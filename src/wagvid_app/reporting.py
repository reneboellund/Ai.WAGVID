"""Persistent, immutable product reports and leakage-safe event batch plans."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator

from ai_wagvid.competition_batch import plan_competition_batch
from wagvid_rules.validation import load_schema

from .models import (
    AnalysisDeliverable,
    AnalysisJob,
    AnalysisResult,
    CompetitionBatchRun,
    Event,
    Membership,
)


def canonical_digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _require_reporter(actor, organization):
    if not actor.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[
            Membership.Role.SYSTEM_ADMIN,
            Membership.Role.ORGANIZATION_ADMIN,
            Membership.Role.REVIEWER,
            Membership.Role.DOMAIN_REVIEWER,
            Membership.Role.COACH,
        ],
    ).exists():
        raise PermissionError("reporting role is required")


def _schema(filename: str):
    from django.conf import settings

    return load_schema(settings.BASE_DIR / "schemas" / filename)


def _validate(payload: dict, filename: str):
    errors = sorted(Draft202012Validator(_schema(filename)).iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        path = ".".join(str(item) for item in errors[0].path) or "$"
        raise ValueError(f"report schema validation failed at {path}: {errors[0].message}")


@transaction.atomic
def generate_score_verification(*, job, actor) -> AnalysisDeliverable:
    job = AnalysisJob.objects.select_for_update().select_related("organization", "media__gymnast", "media__routine__event", "result").get(pk=job.pk)
    _require_reporter(actor, job.organization)
    result = getattr(job, "result", None)
    if not result or result.state != AnalysisResult.State.FROZEN or not result.frozen_at:
        raise ValueError("AI analysis must be frozen before score verification is generated")
    media = job.media
    routine = media.routine
    deductions = list(result.deductions.prefetch_related("decisions__reviewer").order_by("start_ms", "id"))
    deduction_payload = []
    for candidate in deductions:
        latest = candidate.decisions.order_by("-created_at").first()
        deduction_payload.append(
            {
                "id": str(candidate.id),
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "criterion": candidate.criterion,
                "rule_reference": candidate.rule_reference,
                "proposed_amount": str(candidate.proposed_amount),
                "confidence": str(candidate.model_confidence),
                "evidence": candidate.evidence,
                "review_state": candidate.review_state,
                "latest_decision": latest.decision if latest else None,
                "accepted_amount": str(latest.accepted_amount) if latest and latest.accepted_amount is not None else None,
            }
        )
    proposed = {
        "d": str(result.proposed_d_score) if result.proposed_d_score is not None else None,
        "e": str(result.proposed_e_score) if result.proposed_e_score is not None else None,
        "neutral": str(result.proposed_neutral) if result.proposed_neutral is not None else None,
        "final": str(result.proposed_final_score) if result.proposed_final_score is not None else None,
    }
    official = None
    if routine and routine.official_final_score is not None:
        official = {
            "d": str(routine.official_d_score) if routine.official_d_score is not None else None,
            "e": str(routine.official_e_score) if routine.official_e_score is not None else None,
            "neutral": str(routine.official_neutral) if routine.official_neutral is not None else None,
            "final": str(routine.official_final_score),
            "frozen_at": routine.official_frozen_at.isoformat() if routine.official_frozen_at else None,
        }
    payload = {
        "schema": "ai.wagvid.score-verification-report.v1",
        "report_id": str(job.id),
        "analysis": {
            "job_id": str(job.id),
            "revision": job.revision,
            "state": result.state,
            "frozen_at": result.frozen_at.isoformat(),
            "rulepack_id": job.rulepack_id,
            "model_profile": job.model_profile,
            "model_run": result.model_run,
        },
        "source": {
            "media_id": str(media.id),
            "sha256": media.sha256,
            "content_type": media.content_type,
            "size_bytes": media.size_bytes,
            "recorded_at": media.recorded_at.isoformat(),
            "camera": result.model_run.get("camera", {}),
            "quality": result.model_run.get("quality", {}),
        },
        "scores": {"reconstructed": proposed, "official": official},
        "score_ledger": result.score_ledger,
        "deductions": deduction_payload,
        "unresolved": [item["id"] for item in deduction_payload if item["review_state"] == "pending"],
    }
    _validate(payload, "score-verification-report-v1.schema.json")
    revision = job.deliverables.filter(kind=AnalysisDeliverable.Kind.SCORE_VERIFICATION).count() + 1
    deliverable = AnalysisDeliverable.objects.create(
        organization=job.organization,
        kind=AnalysisDeliverable.Kind.SCORE_VERIFICATION,
        schema_id=payload["schema"],
        analysis_job=job,
        gymnast=media.gymnast,
        event=routine.event if routine else None,
        revision=revision,
        payload=payload,
        payload_digest=canonical_digest(payload),
        provenance={
            "media_sha256": media.sha256,
            "rulepack_id": job.rulepack_id,
            "model_profile": job.model_profile,
            "analysis_result_id": str(result.id),
            "analysis_frozen_at": result.frozen_at.isoformat(),
        },
        generated_by=actor,
    )
    job.organization.audit_events.create(
        actor=actor,
        action="report.score-verification-generated",
        object_type="analysis-deliverable",
        object_id=str(deliverable.id),
        metadata={"digest": deliverable.payload_digest, "analysis_job_id": str(job.id), "revision": revision},
    )
    return deliverable


@transaction.atomic
def publish_structured_report(*, organization, actor, kind: str, payload: dict, gymnast=None, event=None) -> AnalysisDeliverable:
    _require_reporter(actor, organization)
    definitions = {
        AnalysisDeliverable.Kind.PERFORMANCE: ("ai.wagvid.performance-report.v1", "performance-report-v1.schema.json"),
        AnalysisDeliverable.Kind.LONGITUDINAL: ("ai.wagvid.longitudinal-report.v1", "longitudinal-report-v1.schema.json"),
    }
    if not isinstance(payload, dict):
        raise TypeError("report payload must be a JSON object")
    if kind not in definitions:
        raise ValueError("unsupported structured report kind")
    schema_id, filename = definitions[kind]
    if payload.get("schema") != schema_id:
        raise ValueError("report schema identifier does not match kind")
    _validate(payload, filename)
    if gymnast and gymnast.organization_id != organization.id:
        raise ValueError("gymnast belongs to another organization")
    if event and event.organization_id != organization.id:
        raise ValueError("event belongs to another organization")
    payload_digest = canonical_digest(payload)
    existing = AnalysisDeliverable.objects.filter(organization=organization, kind=kind, payload_digest=payload_digest).first()
    if existing:
        return existing
    deliverable = AnalysisDeliverable.objects.create(
        organization=organization,
        kind=kind,
        schema_id=schema_id,
        gymnast=gymnast,
        event=event,
        revision=1,
        payload=payload,
        payload_digest=payload_digest,
        provenance={"source_report_digest": payload_digest},
        generated_by=actor,
    )
    organization.audit_events.create(actor=actor, action="report.structured-published", object_type="analysis-deliverable", object_id=str(deliverable.id), metadata={"kind": kind, "digest": deliverable.payload_digest})
    return deliverable


def _event_record(routine) -> dict:
    media = routine.media.filter(state="stored").order_by("recorded_at", "id")
    official = routine.official_versions.order_by("-source_captured_at").first()
    if not official:
        official_payload = {"status": "unavailable", "scores": {}}
    else:
        official_payload = {
            "source": official.source,
            "status": official.status,
            "result_version": official.result_version,
            "captured_at": official.source_captured_at.isoformat(),
            "scores": {"d": str(official.d_score) if official.d_score is not None else None, "e": str(official.e_score) if official.e_score is not None else None, "neutral": str(official.neutral) if official.neutral is not None else None, "final": str(official.final_score)},
        }
    return {
        "schema": "ai.wagvid.competition-video.v1",
        "competition": {"external_id": routine.event.external_id or str(routine.event_id), "rule_profile": routine.rulepack_id},
        "routine": {"external_id": routine.external_id or str(routine.id), "athlete_external_id": routine.gymnast.kiga_id or str(routine.gymnast_id), "team_external_id": None, "apparatus": routine.apparatus, "performed_at": (routine.performed_at or routine.event.starts_at).isoformat()},
        "media": [{"media_id": str(item.id), "sha256": item.sha256, "download_uri": f"wagvid://media/{item.id}", "content_type": item.content_type or "video/mp4", "camera_id": str(item.device_id) if item.device_id else None, "view": None} for item in media],
        "official_result": official_payload,
        "rights": {"analysis_allowed": True, "download_allowed": True},
    }


@transaction.atomic
def plan_event_analysis(*, event: Event, actor, analysis_profile_digest: str) -> CompetitionBatchRun:
    _require_reporter(actor, event.organization)
    existing_request = CompetitionBatchRun.objects.select_for_update().filter(
        organization=event.organization,
        event=event,
        analysis_profile_digest=analysis_profile_digest,
        state=CompetitionBatchRun.State.PLANNED,
    ).first()
    if existing_request:
        return existing_request
    routines = event.routines.select_related("event", "gymnast").prefetch_related("media", "official_versions")
    plan = plan_competition_batch((_event_record(item) for item in routines), batch_id=f"event:{event.id}", analysis_profile_digest=analysis_profile_digest, requested_at=timezone.now())
    control_plan = {
        "schema": "ai.wagvid.competition-batch-control.v1",
        "batch_id": plan.batch_id,
        "requested_at": plan.requested_at.isoformat(),
        "analysis_profile_digest": plan.analysis_profile_digest,
        "tasks": [item.task.worker_payload() for item in plan.routines],
        "withheld_official_digests": [item.withheld_official.official_payload_digest for item in plan.routines],
        "excluded": [{"source_record_digest": item.source_record_digest, "competition_external_id": item.competition_external_id, "routine_external_id": item.routine_external_id, "reasons": list(item.reasons)} for item in plan.excluded],
    }
    existing = CompetitionBatchRun.objects.filter(plan_digest=plan.digest).first()
    if existing:
        if existing.organization_id != event.organization_id or existing.event_id != event.id:
            raise ValueError("batch plan digest is already bound to another event")
        return existing
    run = CompetitionBatchRun.objects.create(
        organization=event.organization,
        event=event,
        analysis_profile_digest=analysis_profile_digest,
        plan_digest=plan.digest,
        task_count=len(plan.routines),
        excluded_count=len(plan.excluded),
        control_plan=control_plan,
        requested_by=actor,
    )
    event.organization.audit_events.create(actor=actor, action="competition.batch-planned", object_type="competition-batch", object_id=str(run.id), metadata={"plan_digest": run.plan_digest, "task_count": run.task_count, "excluded_count": run.excluded_count})
    return run
