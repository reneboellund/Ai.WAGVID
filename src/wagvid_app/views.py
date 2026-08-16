import csv
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .device_operations import DeviceOperationError, create_pairing_offer, enqueue_device_command
from .forms import (
    GymnastForm,
    GymnastImportForm,
    KigaImportForm,
    ReviewDecisionForm,
    ScoreComparisonReviewForm,
)
from .imports import commit_gymnast_import, preview_gymnast_csv
from .kiga import commit_kiga_record, preview_kiga_record
from .kiga_exports import export_kiga_routine
from .learning_exports import reviewed_score_labels
from .models import (
    AnalysisJob,
    DeductionCandidate,
    Device,
    Event,
    ExchangeJob,
    MediaAsset,
    Membership,
    ReviewDecision,
    Routine,
)
from .operations import InvalidStateTransition, cancel_analysis, record_score_comparison_review
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
    pairing_offer = None
    if request.method == "POST":
        try:
            pairing_offer = create_pairing_offer(
                organization=organization, requested_by=request.user
            )
        except PermissionError:
            return HttpResponseForbidden()
    return render(
        request,
        "wagvid/devices.html",
        {
            "organization": organization,
            "devices": organization.devices.prefetch_related("commands"),
            "pairing_offer": pairing_offer,
            "can_manage": can_manage_master_data(request, organization),
        },
    )


@login_required
def operate(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    if request.method == "POST":
        try:
            device = organization.devices.get(pk=request.POST["device_id"])
            command = request.POST["command"]
            payload = {}
            if command in {"start", "arm"}:
                payload = {
                    "capture_id": str(uuid.uuid4()),
                    "gymnast_id": request.POST["gymnast_id"],
                    "kind": request.POST["kind"],
                    "apparatus": request.POST.get("apparatus", ""),
                }
            item, created = enqueue_device_command(
                device_id=device.id,
                requested_by=request.user,
                command=command,
                idempotency_key=request.POST.get("idempotency_key") or str(uuid.uuid4()),
                payload=payload,
            )
            messages.success(
                request,
                f"Kommando {item.get_command_display()} er {'oprettet' if created else 'allerede registreret'}.",
            )
        except PermissionError:
            return HttpResponseForbidden()
        except (Device.DoesNotExist, DeviceOperationError, KeyError, ValueError) as error:
            messages.error(request, str(error))
        return redirect("operate")
    context = {
        "organization": organization,
        "devices": organization.devices.prefetch_related("commands"),
        "gymnasts": organization.gymnasts.filter(archived_at__isnull=True),
        "kind_choices": MediaAsset.Kind.choices,
        "apparatus_choices": Routine.Apparatus.choices,
        "can_control": can_manage_master_data(request, organization),
    }
    return render(request, "wagvid/operate.html", context)


@login_required
def analyses(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    jobs = organization.analysis_jobs.select_related(
        "media", "media__gymnast", "media__routine"
    )
    state = request.GET.get("state", "")
    apparatus = request.GET.get("apparatus", "")
    media_kind = request.GET.get("kind", "")
    query = request.GET.get("q", "").strip()
    if state in AnalysisJob.State.values:
        jobs = jobs.filter(state=state)
    if apparatus:
        jobs = jobs.filter(media__routine__apparatus=apparatus)
    if media_kind in MediaAsset.Kind.values:
        jobs = jobs.filter(media__kind=media_kind)
    if query:
        jobs = jobs.filter(
            Q(media__gymnast__display_name__icontains=query)
            | Q(media__gymnast__license_number__icontains=query)
            | Q(media__routine__event__name__icontains=query)
        )
    jobs = jobs.order_by(
        Case(
            When(state=AnalysisJob.State.NEEDS_REVIEW, then=Value(0)),
            When(state=AnalysisJob.State.FAILED_TERMINAL, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
        "created_at",
    )
    return render(
        request,
        "wagvid/analyses.html",
        {
            "organization": organization,
            "jobs": jobs,
            "filters": {"state": state, "apparatus": apparatus, "kind": media_kind, "q": query},
            "state_choices": AnalysisJob.State.choices,
            "apparatus_choices": Routine.Apparatus.choices,
            "kind_choices": MediaAsset.Kind.choices,
        },
    )


@login_required
def analysis_cancel(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    if request.method != "POST":
        return redirect("analyses")
    job = get_object_or_404(AnalysisJob, pk=job_id, organization=organization)
    try:
        cancel_analysis(job.id, actor=request.user, reason=request.POST.get("reason", ""))
    except PermissionError:
        return HttpResponseForbidden()
    except (InvalidStateTransition, ValueError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Analysejobbet er annulleret og worker-leasen frigivet.")
    return redirect("analyses")


@login_required
def analysis_review(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    job = get_object_or_404(
        AnalysisJob.objects.select_related("media__gymnast", "media__routine__event", "result"),
        pk=job_id,
        organization=organization,
    )
    result = getattr(job, "result", None)
    deductions = result.deductions.prefetch_related("decisions__reviewer") if result else []
    return render(
        request,
        "wagvid/analysis_review.html",
        {
            "organization": organization,
            "job": job,
            "result": result,
            "deductions": deductions,
            "score_review_form": ScoreComparisonReviewForm(),
        },
    )


@login_required
def score_comparison_review(request, job_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    job = get_object_or_404(
        AnalysisJob.objects.select_related("result"), pk=job_id, organization=organization
    )
    if request.method != "POST":
        return redirect("analysis-review", job_id=job.id)
    form = ScoreComparisonReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Den samlede scoreafgørelse er ikke komplet.")
        return redirect("analysis-review", job_id=job.id)
    data = form.cleaned_data
    try:
        record_score_comparison_review(
            result_id=job.result.id,
            reviewer=request.user,
            decision=data["decision"],
            accepted_scores={
                "d_score": data["accepted_d_score"],
                "e_score": data["accepted_e_score"],
                "neutral": data["accepted_neutral"],
                "final_score": data["accepted_final_score"],
            },
            notes=data["notes"],
        )
    except PermissionError:
        return HttpResponseForbidden()
    except (ValueError, AttributeError) as error:
        messages.error(request, str(error))
        return redirect("analysis-review", job_id=job.id)
    messages.success(request, "Scoreafgørelsen er gemt, og analysen er afsluttet.")
    return redirect("analysis-review", job_id=job.id)


@login_required
def review_decision(request, candidate_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    allowed_roles = {
        Membership.Role.SYSTEM_ADMIN,
        Membership.Role.ORGANIZATION_ADMIN,
        Membership.Role.REVIEWER,
    }
    membership = request.user.wagvid_memberships.filter(
        organization=organization, active=True
    ).first()
    if not membership or membership.role not in allowed_roles:
        return HttpResponseForbidden()
    candidate = get_object_or_404(
        DeductionCandidate.objects.select_related("result__analysis_job"),
        pk=candidate_id,
        result__analysis_job__organization=organization,
    )
    if request.method != "POST":
        return redirect("analysis-review", job_id=candidate.result.analysis_job_id)
    form = ReviewDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Afgørelsen mangler påkrævede oplysninger.")
        return redirect("analysis-review", job_id=candidate.result.analysis_job_id)
    decision = form.save(commit=False)
    decision.candidate = candidate
    decision.reviewer = request.user
    decision.save()
    state_map = {
        ReviewDecision.Decision.ACCEPT_AI: DeductionCandidate.ReviewState.ACCEPTED,
        ReviewDecision.Decision.CORRECT_AI: DeductionCandidate.ReviewState.CORRECTED,
        ReviewDecision.Decision.ACCEPT_OFFICIAL: DeductionCandidate.ReviewState.REJECTED,
        ReviewDecision.Decision.OFFICIAL_ERROR: DeductionCandidate.ReviewState.ACCEPTED,
        ReviewDecision.Decision.INCONCLUSIVE: DeductionCandidate.ReviewState.PENDING,
    }
    candidate.review_state = state_map[decision.decision]
    candidate.save(update_fields=["review_state", "updated_at"])
    organization.audit_events.create(
        actor=request.user,
        action="deduction.reviewed",
        object_type="review-decision",
        object_id=str(decision.id),
        reason=decision.notes,
        metadata={"candidate_id": str(candidate.id), "decision": decision.decision},
    )
    messages.success(request, "Afgørelsen er registreret i reviewhistorikken.")
    return redirect("analysis-review", job_id=candidate.result.analysis_job_id)


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
            "kiga_form": KigaImportForm(),
            "preview": preview,
            "can_manage": can_manage_master_data(request, organization),
        },
    )


@login_required
def kiga_import_preview(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    if request.method != "POST":
        return redirect("exchange")
    form = KigaImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "KIGA-filen kunne ikke læses.")
        return redirect("exchange")
    content = form.cleaned_data["json_file"].decoded_text
    preview = preview_kiga_record(organization, content)
    if not preview.valid:
        messages.error(request, "KIGA-importen har fejl: " + "; ".join(preview.errors))
        return redirect("exchange")
    request.session["wagvid_kiga_import"] = content
    return render(
        request,
        "wagvid/kiga_preview.html",
        {"organization": organization, "preview": preview},
    )


@login_required
def kiga_import_commit(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    if request.method != "POST":
        return redirect("exchange")
    content = request.session.pop("wagvid_kiga_import", "")
    preview = preview_kiga_record(organization, content)
    if not preview.valid:
        messages.error(request, "KIGA-importen skal valideres igen.")
        return redirect("exchange")
    event, routine, references, snapshot = commit_kiga_record(organization, preview)
    job = ExchangeJob.objects.create(
        organization=organization,
        direction=ExchangeJob.Direction.IMPORT,
        kind="kiga-competition-video",
        state=ExchangeJob.State.COMPLETED,
        schema_version="competition-video-v1",
        result_summary={
            "event_id": str(event.id),
            "routine_id": str(routine.id),
            "media_references": len(references),
            "official_result_version": snapshot.result_version,
        },
        requested_by=request.user,
    )
    organization.audit_events.create(
        actor=request.user,
        action="kiga.competition-video-imported",
        object_type="exchange-job",
        object_id=str(job.id),
        metadata=job.result_summary,
    )
    messages.success(request, "KIGA-konkurrence, video og officielt resultat er importeret.")
    return redirect("competitions")


@login_required
def competitions(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    events = (
        organization.events.filter(kind=Event.Kind.COMPETITION)
        .prefetch_related("routines__gymnast", "routines__external_media_references")
        .order_by("-starts_at")
    )
    return render(
        request,
        "wagvid/competitions.html",
        {"organization": organization, "events": events},
    )


@login_required
def kiga_routine_export(request, routine_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    routine = get_object_or_404(
        Routine.objects.select_related("event", "gymnast").prefetch_related(
            "external_media_references", "official_versions"
        ),
        pk=routine_id,
        organization=organization,
    )
    try:
        payload = export_kiga_routine(routine)
    except ValueError as error:
        return JsonResponse({"error": "kiga-export-not-ready", "detail": str(error)}, status=409)
    organization.audit_events.create(
        actor=request.user,
        action="kiga.routine-exported",
        object_type="routine",
        object_id=str(routine.id),
        metadata={"schema": payload["schema"]},
    )
    response = JsonResponse(payload)
    response["Content-Disposition"] = f'attachment; filename="wagvid-kiga-{routine.id}.json"'
    return response


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
def gymnast_import_errors(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    csv_text = request.session.get("wagvid_gymnast_import", "")
    if not csv_text:
        return JsonResponse({"error": "no-import-preview"}, status=404)
    preview = preview_gymnast_csv(organization, csv_text)
    response = HttpResponse(preview.error_report_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="wagvid-gymnast-import-errors.csv"'
    response["X-WAGVID-Preview-Digest"] = preview.digest
    return response


@login_required
def gymnast_export(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="wagvid-gymnasts.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["name", "license_number", "discipline", "level", "kiga_id"])
    for gymnast in organization.gymnasts.select_related("level").order_by("display_name"):
        writer.writerow(
            [
                gymnast.display_name,
                gymnast.license_number,
                gymnast.discipline,
                gymnast.level.name,
                gymnast.kiga_id,
            ]
        )
    return response


@login_required
def reviewed_labels_export(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    allowed = request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[
            Membership.Role.SYSTEM_ADMIN,
            Membership.Role.ORGANIZATION_ADMIN,
            Membership.Role.RESEARCHER,
        ],
    ).exists()
    if not allowed:
        return HttpResponseForbidden()
    labels = reviewed_score_labels(organization)
    organization.audit_events.create(
        actor=request.user,
        action="research.reviewed-labels-exported",
        object_type="organization",
        object_id=str(organization.id),
        metadata={"label_count": len(labels), "schema": "reviewed-score-label.v1"},
    )
    response = JsonResponse(
        {"schema": "ai.wagvid.reviewed-score-label-set.v1", "labels": labels}
    )
    response["Content-Disposition"] = 'attachment; filename="wagvid-reviewed-labels.json"'
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
