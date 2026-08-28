"""Operational report and competition-batch views."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import AnalysisDeliverable, AnalysisJob, CompetitionBatchRun, Event
from .reporting import generate_score_verification, plan_event_analysis, publish_structured_report
from .views import active_organization


@login_required
def reports(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(request, "wagvid/reports.html", {
        "organization": organization,
        "reports": organization.analysis_deliverables.select_related("gymnast", "event", "analysis_job")[:100],
        "batches": organization.competition_batches.select_related("event", "requested_by")[:50],
        "gymnasts": organization.gymnasts.filter(archived_at__isnull=True),
        "events": organization.events.filter(kind=Event.Kind.COMPETITION),
        "report_kinds": [(AnalysisDeliverable.Kind.PERFORMANCE, "Performance"), (AnalysisDeliverable.Kind.LONGITUDINAL, "Longitudinal")],
    })


@login_required
def report_detail(request, report_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    report = get_object_or_404(organization.analysis_deliverables.select_related("gymnast", "event", "analysis_job", "generated_by"), pk=report_id)
    return render(request, "wagvid/report_detail.html", {"organization": organization, "report": report, "pretty_payload": json.dumps(report.payload, indent=2, ensure_ascii=False)})


@login_required
def report_json(request, report_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    report = get_object_or_404(organization.analysis_deliverables, pk=report_id)
    response = JsonResponse(report.payload)
    response["Content-Disposition"] = f'attachment; filename="wagvid-{report.kind}-{report.id}.json"'
    response["ETag"] = f'"{report.payload_digest}"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def score_report_generate(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    job = get_object_or_404(AnalysisJob.objects.select_related("organization", "media__gymnast", "media__routine__event", "result"), pk=job_id, organization=organization)
    try:
        report = generate_score_verification(job=job, actor=request.user)
    except (PermissionError, ValueError) as error:
        messages.error(request, str(error))
        return redirect("analysis-review", job_id=job.id)
    messages.success(request, "Den immutable scoreverifikationsrapport er genereret.")
    return redirect("report-detail", report_id=report.id)


@login_required
@require_POST
def structured_report_publish(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.POST.get("payload", "{}"))
        gymnast = organization.gymnasts.filter(pk=request.POST.get("gymnast_id")).first()
        event = organization.events.filter(pk=request.POST.get("event_id")).first()
        report = publish_structured_report(organization=organization, actor=request.user, kind=request.POST.get("kind", ""), payload=payload, gymnast=gymnast, event=event)
    except (TypeError, json.JSONDecodeError, PermissionError, ValueError) as error:
        messages.error(request, str(error))
        return redirect("reports")
    messages.success(request, "Den validerede rapport er publiceret som immutable artifact.")
    return redirect("report-detail", report_id=report.id)


@login_required
@require_POST
def competition_batch_plan(request, event_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    event = get_object_or_404(organization.events, pk=event_id, kind=Event.Kind.COMPETITION)
    try:
        run = plan_event_analysis(event=event, actor=request.user, analysis_profile_digest=request.POST.get("analysis_profile_digest", ""))
    except (PermissionError, ValueError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Batchplanen er oprettet med {run.task_count} identitetsminimerede tasks og {run.excluded_count} udelukkelser.")
    return redirect("reports")


@login_required
def competition_batch_json(request, batch_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    batch = get_object_or_404(CompetitionBatchRun, pk=batch_id, organization=organization)
    response = JsonResponse(batch.control_plan)
    response["Content-Disposition"] = f'attachment; filename="wagvid-competition-batch-{batch.id}.json"'
    response["ETag"] = f'"{batch.plan_digest}"'
    response["Cache-Control"] = "private, no-store"
    return response
