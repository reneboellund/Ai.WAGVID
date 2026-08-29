import csv
import json
import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .backup_recovery import create_backup_plan, restore_preflight, verify_backup
from .device_operations import DeviceOperationError, create_pairing_offer, enqueue_device_command
from .forms import (
    GymnastForm,
    GymnastImportForm,
    KigaImportForm,
    LevelForm,
    ReviewDecisionForm,
    ScoreComparisonReviewForm,
    StorageConnectionForm,
    StorageRoleAssignmentForm,
)
from .imports import commit_gymnast_import, preview_gymnast_csv
from .kiga import commit_kiga_record, preview_kiga_record
from .kiga_exports import export_kiga_routine
from .learning_exports import reviewed_score_labels
from .master_data import archive_gymnast, merge_gymnasts
from .models import (
    AnalysisJob,
    DeductionCandidate,
    Device,
    Event,
    EvidenceAnnotationRevision,
    ExchangeJob,
    Gymnast,
    MaintenanceState,
    MediaAsset,
    Membership,
    ReviewDecision,
    Routine,
    SystemBackup,
    UpgradeJournal,
)
from .operations import InvalidStateTransition, cancel_analysis, record_score_comparison_review
from .runtime import runtime_probes
from .secret_refs import SecretReferenceError
from .services import dashboard_status
from .storage_lifecycle import (
    apply_storage_connection,
    assign_storage_role,
    connection_plan,
    disconnect_storage_connection,
    preflight_storage_connection,
    reconcile_desired_buckets,
    storage_cost_summary,
)
from .storage_types import BucketRole
from .upgrade_ops import plan_upgrade, set_maintenance, transition_upgrade, upgrade_preflight
from .wasabi_provider import WasabiSetupError


def active_organization(request):
    memberships = request.user.wagvid_memberships.filter(
        active=True, organization__active=True
    ).select_related("organization")
    selected = request.session.get("wagvid_organization_id")
    membership = memberships.filter(organization_id=selected).first() if selected else None
    membership = membership or memberships.first()
    return membership.organization if membership else None


def can_manage_master_data(request, organization):
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN],
    ).exists()


def can_manage_system(request, organization):
    """Global recovery data is restricted to explicitly designated system admins."""
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role=Membership.Role.SYSTEM_ADMIN,
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
def storage_settings(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    connections = organization.storage_connections.filter(active=True).order_by("name")
    selected_id = request.POST.get("connection_id") or request.GET.get("connection")
    connection = connections.filter(pk=selected_id).first() if selected_id else connections.first()
    if request.GET.get("new") == "1":
        connection = None
    if request.method == "POST" and request.POST.get("action") == "assign-role":
        assignment_form = StorageRoleAssignmentForm(request.POST, organization=organization)
        if assignment_form.is_valid():
            assign_storage_role(
                organization=organization,
                role=BucketRole(assignment_form.cleaned_data["role"]),
                connection=assignment_form.cleaned_data["connection"],
                actor=request.user,
            )
            messages.success(request, "Storage-rollen er tildelt den valgte provider.")
        else:
            messages.error(request, "Storage-rollen kunne ikke tildeles.")
        return redirect("storage-settings")
    if request.method == "POST" and request.POST.get("action") == "preflight" and connection:
        try:
            result = preflight_storage_connection(connection.id, actor=request.user)
        except (SecretReferenceError, WasabiSetupError, ValueError) as error:
            messages.error(request, f"Wasabi preflight kunne ikke gennemføres: {error}")
        else:
            message = "Preflight er klar til apply." if result.applicable else "Preflight fandt blockers."
            messages.success(request, message)
        return redirect(f"{reverse('storage-settings')}?connection={connection.id}")
    if request.method == "POST" and request.POST.get("action") == "disconnect" and connection:
        try:
            disconnect_storage_connection(
                connection.id,
                actor=request.user,
                reason=request.POST.get("reason", "Afbrudt fra storageadministration"),
            )
        except (PermissionError, ValueError) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Forbindelsen er afbrudt uden at slette buckets eller data.")
        return redirect("storage-settings")
    if request.method == "POST" and request.POST.get("action") == "apply" and connection:
        try:
            completed = apply_storage_connection(
                connection.id,
                actor=request.user,
                confirmation=request.POST.get("confirmation", ""),
            )
        except (SecretReferenceError, WasabiSetupError, PermissionError, ValueError) as error:
            messages.error(request, f"Wasabi-opsætningen blev ikke anvendt: {error}")
        else:
            messages.success(
                request, f"Wasabi-opsætningen er anvendt ({len(completed)} handlinger)."
            )
        return redirect(f"{reverse('storage-settings')}?connection={connection.id}")
    form = StorageConnectionForm(request.POST or None, instance=connection)
    if request.method == "POST" and form.is_valid():
        connection = form.save(commit=False)
        connection.organization = organization
        connection.save()
        buckets = reconcile_desired_buckets(connection.id)
        organization.audit_events.create(
            actor=request.user,
            action="storage.provider-plan-saved",
            object_type="storage-connection",
            object_id=str(connection.id),
            metadata={
                "plan_digest": connection.desired_plan_digest,
                "bucket_count": len(buckets),
                "region": connection.region,
                "provider": connection.provider,
            },
        )
        messages.success(
            request,
            "Storage dry-run planen er gemt lokalt. Ingen buckets blev oprettet.",
        )
        return redirect(f"{reverse('storage-settings')}?connection={connection.id}")
    plan = connection_plan(connection) if connection else None
    return render(
        request,
        "wagvid/storage_settings.html",
        {
            "organization": organization,
            "connection": connection,
            "connections": connections,
            "assignments": organization.storage_role_assignments.filter(active=True).select_related(
                "connection"
            ),
            "assignment_form": StorageRoleAssignmentForm(organization=organization),
            "form": form,
            "plan": plan,
            "buckets": connection.buckets.order_by("role", "shard") if connection else [],
            "cost": storage_cost_summary(organization),
        },
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
            "can_manage": can_manage_master_data(request, organization),
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
def gymnast_edit(request, gymnast_id):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    gymnast = get_object_or_404(organization.gymnasts, pk=gymnast_id)
    form = GymnastForm(request.POST or None, instance=gymnast, organization=organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        organization.audit_events.create(
            actor=request.user, action="gymnast.updated", object_type="gymnast", object_id=str(gymnast.id)
        )
        messages.success(request, "Gymnasten er opdateret.")
        return redirect("gymnasts")
    return render(request, "wagvid/form.html", {"title": "Redigér gymnast", "form": form})


@login_required
def gymnast_archive(request, gymnast_id):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    gymnast = get_object_or_404(organization.gymnasts, pk=gymnast_id)
    if request.method == "POST":
        try:
            archive_gymnast(gymnast.id, actor=request.user, reason=request.POST.get("reason", ""))
        except ValueError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Gymnasten er arkiveret; historikken er bevaret.")
    return redirect("gymnasts")


@login_required
def gymnast_merge(request, gymnast_id):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    source = get_object_or_404(organization.gymnasts, pk=gymnast_id)
    if request.method == "POST":
        try:
            merge_gymnasts(
                source.id,
                uuid.UUID(request.POST.get("target_id", "")),
                actor=request.user,
                reason=request.POST.get("reason", ""),
            )
        except (ValueError, Gymnast.DoesNotExist) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Dubletterne er samlet; alle referencer er flyttet.")
    return redirect("gymnasts")


@login_required
def levels(request, level_id=None):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return HttpResponseForbidden()
    level = get_object_or_404(organization.levels, pk=level_id) if level_id else None
    form = LevelForm(request.POST or None, instance=level)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.organization = organization
        saved.save()
        organization.audit_events.create(
            actor=request.user,
            action="level.updated" if level else "level.created",
            object_type="level",
            object_id=str(saved.id),
        )
        messages.success(request, "Niveauet er gemt.")
        return redirect("levels")
    return render(
        request,
        "wagvid/levels.html",
        {"organization": organization, "levels": organization.levels.order_by("name"), "form": form},
    )


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
        "network_cameras": organization.network_cameras.prefetch_related("actions"),
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
    annotations = job.annotation_revisions.select_related("created_by", "parent").all()
    return render(
        request,
        "wagvid/analysis_review.html",
        {
            "organization": organization,
            "job": job,
            "result": result,
            "deductions": deductions,
            "annotations": annotations,
            "annotation_kinds": EvidenceAnnotationRevision.Kind.choices,
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
        .prefetch_related("kiga_notifications")
        .order_by("-starts_at")
    )
    return render(
        request,
        "wagvid/competitions.html",
        {
            "organization": organization,
            "events": events,
            "can_manage": can_manage_master_data(request, organization),
        },
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


def _can_review(request, organization):
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[
            Membership.Role.SYSTEM_ADMIN,
            Membership.Role.ORGANIZATION_ADMIN,
            Membership.Role.REVIEWER,
        ],
    ).exists()


@login_required
def review_inbox(request):
    organization = active_organization(request)
    if not organization or not _can_review(request, organization):
        return HttpResponseForbidden()
    jobs = organization.analysis_jobs.filter(state=AnalysisJob.State.NEEDS_REVIEW).select_related(
        "media__gymnast", "media__routine", "review_assignee", "result"
    )
    reason = request.GET.get("reason", "").strip()
    apparatus = request.GET.get("apparatus", "").strip()
    assignee = request.GET.get("assignee", "").strip()
    try:
        age_days = max(0, min(3650, int(request.GET.get("age_days", "0"))))
    except ValueError:
        age_days = 0
    if reason:
        jobs = jobs.filter(review_reason=reason)
    if apparatus:
        jobs = jobs.filter(media__routine__apparatus=apparatus)
    if age_days:
        jobs = jobs.filter(created_at__lte=timezone.now() - timedelta(days=age_days))
    if assignee == "me":
        jobs = jobs.filter(review_assignee=request.user)
    elif assignee == "unassigned":
        jobs = jobs.filter(review_assignee__isnull=True)
    return render(
        request,
        "wagvid/review_inbox.html",
        {
            "organization": organization,
            "jobs": jobs.order_by("-review_priority", "created_at"),
            "filters": {"reason": reason, "apparatus": apparatus, "assignee": assignee, "age_days": age_days},
            "apparatus_choices": Routine.Apparatus.choices,
            "reviewers": organization.memberships.filter(
                active=True,
                role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN, Membership.Role.REVIEWER],
            ).select_related("user"),
        },
    )


@login_required
def review_assign(request, job_id):
    organization = active_organization(request)
    if not organization or not _can_review(request, organization):
        return HttpResponseForbidden()
    job = get_object_or_404(organization.analysis_jobs, pk=job_id)
    if request.method == "POST":
        member = get_object_or_404(
            organization.memberships,
            user_id=request.POST.get("assignee_id"),
            active=True,
            role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN, Membership.Role.REVIEWER],
        )
        job.review_assignee = member.user
        job.save(update_fields=["review_assignee", "updated_at"])
        organization.audit_events.create(
            actor=request.user,
            action="analysis.review-assigned",
            object_type="analysis-job",
            object_id=str(job.id),
            metadata={"assignee_id": str(member.user_id)},
        )
        messages.success(request, "Reviewet er tildelt.")
    return redirect("review-inbox")


def _release_manifest():
    path = settings.BASE_DIR / "release" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


@login_required
def system_backups(request):
    organization = active_organization(request)
    if not organization or not can_manage_system(request, organization):
        return HttpResponseForbidden()
    if request.method == "POST" and request.POST.get("action") == "create":
        manifest = _release_manifest()
        purpose = request.POST.get("purpose", SystemBackup.Purpose.MANUAL)
        if purpose not in SystemBackup.Purpose.values:
            return JsonResponse({"error": "invalid-backup-purpose"}, status=400)
        backup = create_backup_plan(
            requested_by=request.user,
            purpose=purpose,
            destination=request.POST.get("destination", "operator-managed"),
            release=manifest["version"],
            git_sha=manifest["git_sha"],
        )
        messages.success(request, f"Backupplan {backup.id} er oprettet; artifact skal nu produceres af runneren.")
        return redirect("system-backups")
    if request.method == "POST" and request.POST.get("action") == "verify":
        try:
            verify_backup(
                request.POST["backup_id"],
                database_sha256=request.POST.get("database_sha256", "").lower(),
                actor=request.user,
            )
        except (KeyError, ValueError, SystemBackup.DoesNotExist) as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Backupverifikationen er registreret.")
        return redirect("system-backups")
    backups = SystemBackup.objects.select_related("requested_by").order_by("-created_at")[:50]
    return render(request, "wagvid/system_backups.html", {"organization": organization, "backups": backups})


@login_required
def backup_manifest(request, backup_id):
    organization = active_organization(request)
    if not organization or not can_manage_system(request, organization):
        return HttpResponseForbidden()
    backup = get_object_or_404(SystemBackup, pk=backup_id)
    response = JsonResponse(backup.manifest)
    response["Content-Disposition"] = f'attachment; filename="wagvid-backup-{backup.id}.json"'
    return response


@login_required
def backup_restore_preflight(request, backup_id):
    organization = active_organization(request)
    if not organization or not can_manage_system(request, organization):
        return HttpResponseForbidden()
    backup = get_object_or_404(SystemBackup, pk=backup_id)
    available = {
        ref for ref in backup.manifest.get("required_secret_references", [])
        if ref.startswith("env:") and os.environ.get(ref.removeprefix("env:"))
    }
    return JsonResponse(restore_preflight(backup, available_secret_references=available))


@login_required
def system_updates(request):
    organization = active_organization(request)
    if not organization or not can_manage_system(request, organization):
        return HttpResponseForbidden()
    manifest = _release_manifest()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "enter-maintenance":
                set_maintenance(actor=request.user, active=True, reason=request.POST.get("reason", ""))
                messages.success(request, "Vedligeholdelsestilstand er aktiv; normale writes afvises.")
            elif action == "leave-maintenance":
                set_maintenance(actor=request.user, active=False, reason="")
                messages.success(request, "Vedligeholdelsestilstand er afsluttet.")
            elif action == "plan":
                journal = plan_upgrade(
                    actor=request.user,
                    source_release=request.POST.get("source_release", "unknown"),
                    target_manifest=manifest,
                )
                messages.success(request, f"Opgraderingsplanen er gemt med status {journal.state}.")
            elif action in {"approve", "start", "begin-verification", "complete", "fail", "stage-rollback"}:
                verification = None
                if action == "complete":
                    verification = {
                        key: request.POST.get(key) == "on"
                        for key in (
                            "migrations_match", "django_checks_pass", "storage_healthy",
                            "backup_catalog_readable", "authentication_works",
                        )
                    }
                journal = transition_upgrade(
                    journal_id=request.POST.get("journal_id"), actor=request.user,
                    action=action, verification=verification,
                )
                messages.success(request, f"Opgraderingen er nu: {journal.get_state_display()}.")
        except (ValueError, UpgradeJournal.DoesNotExist) as error:
            messages.error(request, str(error))
        return redirect("system-updates")
    preflight = upgrade_preflight(target_manifest=manifest)
    return render(
        request,
        "wagvid/system_updates.html",
        {
            "organization": organization,
            "manifest": manifest,
            "preflight": preflight,
            "maintenance": MaintenanceState.objects.filter(pk=1).first(),
            "journals": UpgradeJournal.objects.select_related("initiated_by", "backup")[:25],
        },
    )


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
