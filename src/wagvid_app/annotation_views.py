"""Organization-scoped annotation UI actions."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .annotation_operations import create_annotation_revision
from .models import AnalysisJob
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
