"""Organization administration and governance UI endpoints."""

import csv
import json
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .governance import (
    accept_invitation,
    change_member_role,
    create_configuration_revision,
    create_evidence_share,
    invite_member,
    register_dataset_source,
    revoke_evidence_share,
    validate_evidence_share,
)
from .models import EvidenceShareGrant, Membership
from .object_access import ObjectAccessGrant, sign_object_access
from .views import active_organization, can_manage_master_data


def _admin_context(request):
    organization = active_organization(request)
    if not organization or not can_manage_master_data(request, organization):
        return None
    return organization


@login_required
def organization_select(request):
    memberships = request.user.wagvid_memberships.filter(active=True, organization__active=True).select_related("organization")
    if request.method == "POST":
        membership = get_object_or_404(memberships, organization_id=request.POST.get("organization_id"))
        request.session["wagvid_organization_id"] = str(membership.organization_id)
        target = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = reverse("dashboard")
        return redirect(target)
    return render(request, "wagvid/organization_select.html", {"memberships": memberships})


@login_required
def governance_admin(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/governance_admin.html",
        {
            "organization": organization,
            "memberships": organization.memberships.select_related("user").order_by("user__username"),
            "roles": Membership.Role.choices,
            "invitations": organization.invitations.order_by("-created_at")[:25],
            "configurations": organization.configuration_revisions.order_by("namespace", "-revision")[:50],
            "datasets": organization.dataset_governance_records.order_by("-created_at")[:50],
            "shares": organization.evidence_share_grants.select_related("media").order_by("-created_at")[:50],
            "media_assets": organization.media.order_by("-recorded_at")[:100],
            "audit_events": organization.audit_events.select_related("actor")[:100],
        },
    )


@login_required
@require_POST
def member_invite(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    try:
        invitation, raw_token = invite_member(organization=organization, actor=request.user, email=request.POST.get("email", ""), role=request.POST.get("role", ""))
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
    else:
        request.session["wagvid_last_invitation_token"] = raw_token
        messages.success(request, f"Invitation oprettet til {invitation.email}. Token vises kun én gang: {raw_token}")
    return redirect("governance-admin")


@login_required
@require_POST
def invitation_accept(request):
    try:
        invitation = accept_invitation(raw_token=request.POST.get("token", ""), user=request.user)
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
        return redirect("organization-select")
    request.session["wagvid_organization_id"] = str(invitation.organization_id)
    messages.success(request, "Invitationen er accepteret.")
    return redirect("dashboard")


@login_required
@require_POST
def member_change(request, membership_id):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    membership = get_object_or_404(organization.memberships, pk=membership_id)
    try:
        change_member_role(membership=membership, actor=request.user, role=request.POST.get("role", ""), active=request.POST.get("active") == "on", reason=request.POST.get("reason", ""))
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Rolle/adgang er opdateret og audit-logget.")
    return redirect("governance-admin")


@login_required
@require_POST
def configuration_create(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    try:
        values = json.loads(request.POST.get("values", "{}"))
        create_configuration_revision(organization=organization, actor=request.user, namespace=request.POST.get("namespace", ""), values=values, reason=request.POST.get("reason", ""), freeze=request.POST.get("freeze") == "on")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Ny konfigurationsrevision er oprettet.")
    return redirect("governance-admin")


@login_required
@require_POST
def dataset_register(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    try:
        register_dataset_source(
            organization=organization, actor=request.user, source_reference=request.POST.get("source_reference", ""), immutable_digest=request.POST.get("immutable_digest", ""),
            rights_reference=request.POST.get("rights_reference", ""), consent_reference=request.POST.get("consent_reference", ""),
            analysis_allowed=request.POST.get("analysis_allowed") == "on", retention_allowed=request.POST.get("retention_allowed") == "on",
            training_allowed=request.POST.get("training_allowed") == "on", export_allowed=request.POST.get("export_allowed") == "on",
            athlete_group=request.POST.get("athlete_group", ""), event_group=request.POST.get("event_group", ""), split_manifest_digest=request.POST.get("split_manifest_digest", ""),
        )
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Datasetkilden er registreret med eksplicitte rettigheder.")
    return redirect("governance-admin")


@login_required
@require_POST
def evidence_share_create(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    media = get_object_or_404(organization.media, pk=request.POST.get("media_id"))
    try:
        _grant, raw_token = create_evidence_share(media=media, actor=request.user, recipient=request.POST.get("recipient", ""), actions=request.POST.getlist("actions"), ttl_minutes=int(request.POST.get("ttl_minutes", "30")))
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"Evidensdelingen er oprettet. Token vises kun én gang: {raw_token}")
    return redirect("governance-admin")


@login_required
@require_POST
def evidence_share_revoke(request, grant_id):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    grant = get_object_or_404(EvidenceShareGrant, pk=grant_id, organization=organization)
    try:
        revoke_evidence_share(grant=grant, actor=request.user, reason=request.POST.get("reason", ""))
    except (ValueError, PermissionError) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Evidensdelingen er tilbagekaldt.")
    return redirect("governance-admin")


@login_required
def audit_export(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    events = organization.audit_events.select_related("actor").order_by("occurred_at", "id")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="wagvid-audit.csv"'
    response.write("\ufeff")
    def safe(value):
        text = str(value)
        return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text

    writer = csv.writer(response)
    writer.writerow(["id", "occurred_at", "actor", "action", "object_type", "object_id", "reason", "correlation_id", "metadata_json"])
    for event in events:
        writer.writerow([safe(event.id), safe(event.occurred_at.isoformat()), safe(event.actor.username if event.actor else "system"), safe(event.action), safe(event.object_type), safe(event.object_id), safe(event.reason), safe(event.correlation_id), safe(json.dumps(event.metadata, sort_keys=True))])
    organization.audit_events.create(actor=request.user, action="audit.exported", object_type="organization", object_id=str(organization.id), metadata={"event_count": events.count(), "format": "csv"})
    return response


@login_required
def dataset_governance_export(request):
    organization = _admin_context(request)
    if not organization:
        return HttpResponseForbidden()
    records = list(organization.dataset_governance_records.values("id", "source_reference", "immutable_digest", "rights_reference", "consent_reference", "analysis_allowed", "retention_allowed", "training_allowed", "export_allowed", "pseudonymous_athlete_key", "pseudonymous_event_key", "split_manifest_digest", "label_provenance"))
    return JsonResponse({"schema": "ai.wagvid.dataset-governance-set.v1", "organization_id": str(organization.id), "records": records})


@login_required
@require_POST
def evidence_share_redeem(request):
    try:
        grant = validate_evidence_share(raw_token=request.POST.get("token", ""), user=request.user, action=request.POST.get("action", "view"))
    except (EvidenceShareGrant.DoesNotExist, PermissionError) as error:
        return JsonResponse({"error": "share-denied", "detail": str(error)}, status=403)
    media = grant.media
    disposition = "attachment" if request.POST.get("action") == "download" else "inline"
    expires_at = min(int(grant.expires_at.timestamp()), int(time.time()) + settings.WAGVID_OBJECT_GRANT_TTL_SECONDS)
    access = ObjectAccessGrant(str(grant.organization_id), media.object_key, expires_at, disposition, media.sha256)
    token = sign_object_access(access, secret=settings.WAGVID_OBJECT_SIGNING_SECRET)
    return JsonResponse({"url": f"{reverse('media-object-download', args=[media.id])}?access={token}", "expires_at": expires_at, "share_id": str(grant.id)})
