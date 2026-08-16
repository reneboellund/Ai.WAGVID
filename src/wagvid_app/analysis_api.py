import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import MediaAsset, Membership
from .operations import queue_analysis


def _active_organization(request: HttpRequest):
    memberships = Membership.objects.filter(
        user=request.user, active=True, organization__active=True
    ).select_related("organization")
    organization_slug = request.headers.get("X-WAGVID-Organization")
    membership = (
        memberships.filter(organization__slug=organization_slug).first()
        if organization_slug
        else memberships.first()
    )
    return membership.organization if membership else None


def _job_payload(job) -> dict:
    result = getattr(job, "result", None)
    return {
        "analysis_id": str(job.id),
        "media_id": str(job.media_id),
        "state": job.state,
        "progress_percent": job.progress_percent,
        "revision": job.revision,
        "scope": job.scope,
        "rulepack_id": job.rulepack_id,
        "model_profile": job.model_profile,
        "result": (
            {
                "state": result.state,
                "proposed_d_score": result.proposed_d_score,
                "proposed_e_score": result.proposed_e_score,
                "proposed_neutral": result.proposed_neutral,
                "proposed_final_score": result.proposed_final_score,
            }
            if result
            else None
        ),
    }


@login_required
@require_POST
def analyses_create(request: HttpRequest) -> JsonResponse:
    organization = _active_organization(request)
    if not organization:
        return JsonResponse({"error": "active-organization-required"}, status=403)
    try:
        payload = json.loads(request.body)
        media = MediaAsset.objects.get(
            pk=UUID(payload["media_id"]), organization=organization
        )
        job, created = queue_analysis(
            organization=organization,
            media=media,
            client_request_id=str(payload["client_request_id"]),
            scope=str(payload["scope"]),
            rulepack_id=str(payload["rulepack_id"]),
            model_profile=str(payload["model_profile"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, MediaAsset.DoesNotExist) as error:
        return JsonResponse({"error": "invalid-analysis-request", "detail": str(error)}, status=400)
    return JsonResponse(_job_payload(job), status=201 if created else 200)


@login_required
@require_GET
def analysis_detail(request: HttpRequest, analysis_id: UUID) -> JsonResponse:
    organization = _active_organization(request)
    if not organization:
        return JsonResponse({"error": "active-organization-required"}, status=403)
    job = organization.analysis_jobs.select_related("result").filter(pk=analysis_id).first()
    if not job:
        return JsonResponse({"error": "analysis-not-found"}, status=404)
    return JsonResponse(_job_payload(job))
