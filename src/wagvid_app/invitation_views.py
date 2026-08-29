"""Organization invitation administration and public single-use acceptance views."""

from __future__ import annotations

from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .invitation_operations import (
    InvitationError,
    accept_invitation,
    create_invitation,
    lookup_invitation,
    normalize_email,
    revoke_invitation,
)
from .membership_invitations import MembershipInvitation
from .models import Membership
from .organization_context import active_organization

User = get_user_model()


class InvitationCreateForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    role = forms.ChoiceField(label="Rolle", choices=Membership.Role.choices)

    def __init__(self, *args, actor_membership: Membership, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(Membership.Role.choices)
        if actor_membership.role != Membership.Role.SYSTEM_ADMIN:
            choices = [item for item in choices if item[0] != Membership.Role.SYSTEM_ADMIN]
        self.fields["role"].choices = choices

    def clean_email(self):
        try:
            return normalize_email(self.cleaned_data["email"])
        except ValidationError as error:
            raise forms.ValidationError(error.messages) from error


class InvitationSignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def __init__(self, *args, invitation: MembershipInvitation, **kwargs):
        self.invitation = invitation
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Vælg et brugernavn til Ai.WAGVID."

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.invitation.email
        if commit:
            user.save()
        return user


def _admin_membership(request, organization):
    if organization is None:
        return None
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN],
    ).first()


@login_required
def invitation_list(request):
    organization = active_organization(request)
    actor_membership = _admin_membership(request, organization)
    if actor_membership is None:
        return HttpResponseForbidden()
    invitations = organization.membership_invitations.select_related(
        "created_by", "accepted_by"
    ).order_by("-created_at")[:100]
    return render(
        request,
        "wagvid/invitations.html",
        {
            "organization": organization,
            "invitations": invitations,
            "actor_membership": actor_membership,
        },
    )


@login_required
def invitation_create(request):
    organization = active_organization(request)
    actor_membership = _admin_membership(request, organization)
    if actor_membership is None:
        return HttpResponseForbidden()
    form = InvitationCreateForm(
        request.POST or None,
        actor_membership=actor_membership,
    )
    if request.method == "POST" and form.is_valid():
        try:
            grant = create_invitation(
                organization,
                actor=request.user,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
            )
        except (InvitationError, PermissionDenied) as error:
            form.add_error(None, str(error))
        else:
            accept_path = reverse(
                "membership-invitation-accept",
                kwargs={"token": grant.token},
            )
            return render(
                request,
                "wagvid/invitation_created.html",
                {
                    "organization": organization,
                    "invitation": grant.invitation,
                    # The raw token is deliberately exposed only in this one response.
                    "invitation_url": request.build_absolute_uri(accept_path),
                },
            )
    return render(
        request,
        "wagvid/member_form.html",
        {
            "organization": organization,
            "title": "Invitér bruger",
            "form": form,
        },
    )


@login_required
@require_POST
def invitation_revoke(request, invitation_id):
    organization = active_organization(request)
    if _admin_membership(request, organization) is None:
        return HttpResponseForbidden()
    try:
        revoke_invitation(invitation_id, organization=organization, actor=request.user)
    except MembershipInvitation.DoesNotExist as error:
        raise Http404 from error
    except (InvitationError, PermissionDenied) as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Invitationen er tilbagekaldt.")
    return redirect("membership-invitations")


def invitation_accept(request, token):
    try:
        state = lookup_invitation(token)
    except InvitationError as error:
        raise Http404 from error
    invitation = state.invitation
    if not state.pending:
        return render(
            request,
            "wagvid/invitation_accept.html",
            {"invitation": invitation, "state": state, "form": None},
            status=410,
        )

    if request.user.is_authenticated:
        if request.method == "POST":
            try:
                accept_invitation(token, user=request.user)
            except PermissionDenied:
                return HttpResponseForbidden(
                    "Invitationens e-mail matcher ikke den indloggede bruger."
                )
            except InvitationError as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    f"Du har nu adgang til {invitation.organization.name}.",
                )
                return redirect("workspaces")
        return render(
            request,
            "wagvid/invitation_accept.html",
            {"invitation": invitation, "state": state, "form": None},
        )

    existing = User.objects.filter(email__iexact=invitation.email)
    if existing.exists():
        next_path = reverse("membership-invitation-accept", kwargs={"token": token})
        login_url = f"{reverse('login')}?{urlencode({'next': next_path})}"
        return render(
            request,
            "wagvid/invitation_accept.html",
            {
                "invitation": invitation,
                "state": state,
                "form": None,
                "login_url": login_url,
                "existing_account": True,
            },
        )

    form = InvitationSignupForm(request.POST or None, invitation=invitation)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                # Re-check inside the transaction so a newly appearing existing account is not
                # silently duplicated during the invitation signup flow.
                if User.objects.filter(email__iexact=invitation.email).exists():
                    raise InvitationError(
                        "Der findes nu en konto med denne e-mail. Log ind og brug invitationen igen."
                    )
                user = form.save()
                accept_invitation(token, user=user)
        except InvitationError as error:
            form.add_error(None, str(error))
        else:
            login(request, user)
            messages.success(
                request,
                f"Din konto er oprettet med adgang til {invitation.organization.name}.",
            )
            return redirect("workspaces")

    return render(
        request,
        "wagvid/invitation_accept.html",
        {"invitation": invitation, "state": state, "form": form},
    )
