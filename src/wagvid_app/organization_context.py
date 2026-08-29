"""Per-user active workspace selection without changing membership access semantics."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

SESSION_KEY = "wagvid_active_organization_id"


def active_memberships(request):
    if not request.user.is_authenticated:
        return request.user.wagvid_memberships.none()
    return (
        request.user.wagvid_memberships.filter(active=True, organization__active=True)
        .select_related("organization")
        .order_by("organization__name", "pk")
    )


def active_organization(request):
    memberships = active_memberships(request)
    selected_id = request.session.get(SESSION_KEY)
    if selected_id:
        selected = memberships.filter(organization_id=selected_id).first()
        if selected:
            return selected.organization
        request.session.pop(SESSION_KEY, None)
    membership = memberships.first()
    return membership.organization if membership else None


@login_required
def workspaces(request):
    memberships = list(active_memberships(request))
    if not memberships:
        return HttpResponseForbidden("Ingen aktiv Ai.WAGVID-organisation")
    current = active_organization(request)
    return render(
        request,
        "wagvid/workspaces.html",
        {
            "organization": current,
            "memberships": memberships,
            "current_organization": current,
        },
    )


@login_required
@require_POST
def workspace_switch(request, organization_id):
    membership = active_memberships(request).filter(organization_id=organization_id).first()
    if not membership:
        return HttpResponseForbidden("Du har ikke aktiv adgang til dette workspace.")
    previous = active_organization(request)
    request.session[SESSION_KEY] = str(membership.organization_id)
    membership.organization.audit_events.create(
        actor=request.user,
        action="workspace.selected",
        object_type="organization",
        object_id=str(membership.organization_id),
        metadata={"previous_organization_id": str(previous.id) if previous else ""},
    )
    messages.success(request, f"Aktivt workspace er nu {membership.organization.name}.")
    return redirect("dashboard")
