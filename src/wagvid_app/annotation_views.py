"""Organization-scoped annotation UI actions."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .annotation_operations import create_annotation_revision, revise_annotation
from .models import AnalysisJob, EvidenceAnnotationRevision
from .views import active_organization


@login_required
@require_POST
def annotation_create(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    job = get_object_or_404(AnalysisJob, pk=job_id, organization=organization)
    try:
        create_annotation_revision(
            job=job,
            actor=request.user,
            kind=request.POST.get("kind", ""),
            label=request.POST.get("label", ""),
            start_frame_index=int(request.POST.get("start_frame_index", "")),
            end_frame_index=int(request.POST.get("end_frame_index", "")),
            state=request.POST.get("state", "draft"),
            rule_reference=request.POST.get("rule_reference", ""),
            comment=request.POST.get("comment", ""),
        )
    except (PermissionError, TypeError, ValueError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Annotationen er bundet til canonical frames og gemt som en immutable revision.")
    return redirect("analysis-review", job_id=job.id)


@login_required
@require_POST
def annotation_revise(request, annotation_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    annotation = get_object_or_404(
        EvidenceAnnotationRevision.objects.select_related("analysis_job", "organization", "parent"),
        pk=annotation_id,
        organization=organization,
    )
    try:
        revise_annotation(
            annotation=annotation,
            actor=request.user,
            state=request.POST.get("state", ""),
            label=request.POST.get("label", ""),
            comment=request.POST.get("comment", ""),
        )
    except (PermissionError, TypeError, ValueError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "En ny immutable annotationrevision er gemt.")
    return redirect("analysis-review", job_id=annotation.analysis_job_id)


@login_required
def annotation_export(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    job = get_object_or_404(
        AnalysisJob.objects.select_related("media__gymnast", "media__routine__event"),
        pk=job_id,
        organization=organization,
    )
    latest_by_root = {}
    for item in job.annotation_revisions.select_related("parent", "created_by"):
        root_id = item.parent_id or item.id
        current = latest_by_root.get(root_id)
        if current is None or item.revision > current.revision:
            latest_by_root[root_id] = item
    latest = [
        item
        for item in latest_by_root.values()
        if item.state == EvidenceAnnotationRevision.State.ACCEPTED
    ]
    payload = {
        "schema": "ai.wagvid.annotation-export.v1",
        "analysis_job_id": str(job.id),
        "source_sha256": job.media.sha256,
        "groups": {
            "athlete": str(job.media.gymnast_id),
            "routine": str(job.media.routine_id) if job.media.routine_id else None,
            "event": str(job.media.routine.event_id) if job.media.routine_id else None,
        },
        "labels": [
            {
                "annotation_id": str(item.parent_id or item.id),
                "revision": item.revision,
                "kind": item.kind,
                "label": item.label,
                "source_sha256": item.source_sha256,
                "timeline_digest": item.timeline_digest,
                "stream_index": item.stream_index,
                "start_frame_index": item.start_frame_index,
                "end_frame_index": item.end_frame_index,
                "start_timestamp_ticks": item.start_timestamp_ticks,
                "end_timestamp_ticks": item.end_timestamp_ticks,
                "time_base": [item.time_base_numerator, item.time_base_denominator],
                "rule_reference": item.rule_reference or None,
                "reviewer_id": str(item.created_by_id),
            }
            for item in latest
        ],
    }
    response = JsonResponse(payload)
    response["Content-Disposition"] = f'attachment; filename="annotations-{job.id}.json"'
    response["Cache-Control"] = "private, no-store"
    return response
