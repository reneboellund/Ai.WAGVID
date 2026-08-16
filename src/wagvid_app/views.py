import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from .forms import GymnastForm, GymnastImportForm
from .imports import commit_gymnast_import, preview_gymnast_csv
from .models import ExchangeJob, Membership
from .runtime import runtime_probes
from .services import dashboard_status


def active_organization(request):
    membership = (
        request.user.wagvid_memberships.filter(active=True, organization__active=True)
        .select_related("organization")
        .first()
    )
    return membership.organization if membership else None


def can_manage_master_data(request, organization):
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN],
    ).exists()


@login_required
def dashboard(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden("Ingen aktiv Ai.WAGVID-organisation")
    return render(
        request,
        "wagvid/dashboard.html",
        {"organization": organization, "status": dashboard_status(organization)},
    )


@login_required
def gymnasts(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/gymnasts.html",
        {
            "organization": organization,
            "gymnasts": organization.gymnasts.filter(archived_at__isnull=True).select_related(
                "level"
            ),
        },
    )


@login_required
def gymnast_create(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    membership = request.user.wagvid_memberships.get(organization=organization)
    if membership.role not in {Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN}:
        return HttpResponseForbidden()
    form = GymnastForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        gymnast = form.save(commit=False)
        gymnast.organization = organization
        gymnast.save()
        organization.audit_events.create(
            actor=request.user,
            action="gymnast.created",
            object_type="gymnast",
            object_id=str(gymnast.id),
        )
        return redirect("gymnasts")
    return render(request, "wagvid/form.html", {"title": "Opret gymnast", "form": form})


@login_required
def devices(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/devices.html",
        {"organization": organization, "devices": organization.devices.all()},
    )


@login_required
def operate(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    context = {
        "organization": organization,
        "devices": organization.devices.all(),
        "gymnasts": organization.gymnasts.filter(archived_at__isnull=True),
    }
    return render(request, "wagvid/operate.html", context)


@login_required
def analyses(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/analyses.html",
        {
            "organization": organization,
            "jobs": organization.analysis_jobs.select_related("media", "media__gymnast"),
        },
    )


@login_required
def exchange(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    preview = None
    form = GymnastImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not can_manage_master_data(request, organization):
            return HttpResponseForbidden()
        if form.is_valid():
            csv_text = form.cleaned_data["csv_file"].decoded_text
            preview = preview_gymnast_csv(organization, csv_text)
            request.session["wagvid_gymnast_import"] = csv_text
    return render(
        request,
        "wagvid/exchange.html",
        {
            "organization": organization,
            "jobs": organization.exchange_jobs.all(),
            "form": form,
            "preview": preview,
            "can_manage": can_manage_master_data(request, organization),
        },
    )


@login_required
def gymnast_import_commit(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    if request.method != "POST":
        return redirect("exchange")
    csv_text = request.session.pop("wagvid_gymnast_import", "")
    preview = preview_gymnast_csv(organization, csv_text)
    if not preview.can_commit:
        messages.error(request, "Importen kunne ikke gennemføres; kør preview igen.")
        return redirect("exchange")
    created = commit_gymnast_import(organization, preview)
    job = ExchangeJob.objects.create(
        organization=organization,
        direction=ExchangeJob.Direction.IMPORT,
        kind="gymnasts-csv",
        state=ExchangeJob.State.COMPLETED,
        schema_version="gymnasts-v1",
        result_summary={"created": len(created)},
        requested_by=request.user,
    )
    organization.audit_events.create(
        actor=request.user,
        action="gymnasts.imported",
        object_type="exchange-job",
        object_id=str(job.id),
        metadata={"created": len(created)},
    )
    messages.success(request, f"{len(created)} gymnaster blev importeret.")
    return redirect("exchange")


@login_required
def gymnast_export(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="wagvid-gymnasts.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["name", "license_number", "level", "kiga_id"])
    for gymnast in organization.gymnasts.select_related("level").order_by("display_name"):
        writer.writerow(
            [gymnast.display_name, gymnast.license_number, gymnast.level.name, gymnast.kiga_id]
        )
    return response


@login_required
def system_status(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/system_status.html",
        {
            "organization": organization,
            "status": dashboard_status(organization),
            "probes": runtime_probes(),
        },
    )


def health(request):
    return JsonResponse({"status": "ok", "service": "ai-wagvid-web"})


def readiness(request):
    try:
        probes = runtime_probes()
    except DatabaseError:
        return JsonResponse({"status": "unavailable", "database": "failed"}, status=503)
    payload = {probe.name: probe.status for probe in probes}
    blocking = any(probe.status in {"degraded", "unavailable"} for probe in probes)
    return JsonResponse(
        {"status": "degraded" if blocking else "ready", **payload},
        status=503 if blocking else 200,
    )
