from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from .forms import GymnastForm
from .models import Membership
from .runtime import runtime_probes
from .services import dashboard_status


def active_organization(request):
    membership = request.user.wagvid_memberships.filter(active=True, organization__active=True).select_related("organization").first()
    return membership.organization if membership else None


@login_required
def dashboard(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden("Ingen aktiv Ai.WAGVID-organisation")
    return render(request, "wagvid/dashboard.html", {"organization": organization, "status": dashboard_status(organization)})


@login_required
def gymnasts(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(request, "wagvid/gymnasts.html", {"organization": organization, "gymnasts": organization.gymnasts.filter(archived_at__isnull=True).select_related("level")})


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
        organization.audit_events.create(actor=request.user, action="gymnast.created", object_type="gymnast", object_id=str(gymnast.id))
        return redirect("gymnasts")
    return render(request, "wagvid/form.html", {"title": "Opret gymnast", "form": form})


@login_required
def devices(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(request, "wagvid/devices.html", {"organization": organization, "devices": organization.devices.all()})


@login_required
def operate(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    context = {"organization": organization, "devices": organization.devices.all(), "gymnasts": organization.gymnasts.filter(archived_at__isnull=True)}
    return render(request, "wagvid/operate.html", context)


@login_required
def analyses(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(request, "wagvid/analyses.html", {"organization": organization, "jobs": organization.analysis_jobs.select_related("media", "media__gymnast")})


@login_required
def exchange(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(request, "wagvid/exchange.html", {"organization": organization, "jobs": organization.exchange_jobs.all()})


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
