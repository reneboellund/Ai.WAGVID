"""Organization membership and role administration."""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from .models import Membership
from .views import active_organization, can_manage_master_data

User = get_user_model()
ADMIN_ROLES = {Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN}


def _allowed_role_choices(actor_membership):
    choices = list(Membership.Role.choices)
    if actor_membership.role != Membership.Role.SYSTEM_ADMIN:
        choices = [item for item in choices if item[0] != Membership.Role.SYSTEM_ADMIN]
    return choices


class MembershipCreateForm(forms.Form):
    user_lookup = forms.CharField(
        label="Brugernavn eller e-mail",
        help_text="Brugeren skal allerede eksistere i Ai.WAGVID.",
    )
    role = forms.ChoiceField(label="Rolle", choices=Membership.Role.choices)

    def __init__(self, *args, actor_membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = _allowed_role_choices(actor_membership)

    def clean_user_lookup(self):
        value = self.cleaned_data["user_lookup"].strip()
        matches = User.objects.filter(Q(username__iexact=value) | Q(email__iexact=value)).distinct()
        if matches.count() != 1:
            raise forms.ValidationError("Find præcis én eksisterende bruger via brugernavn eller e-mail.")
        return matches.get()


class MembershipEditForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ["role", "active"]

    def __init__(self, *args, actor_membership, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = _allowed_role_choices(actor_membership)


def _organization(request):
    return active_organization(request)


def _actor_admin_membership(request, organization):
    if not organization:
        return None
    return request.user.wagvid_memberships.filter(
        organization=organization,
        active=True,
        role__in=ADMIN_ROLES,
    ).first()


def _can_manage(request, organization):
    return bool(organization and can_manage_master_data(request, organization))


def _locked_active_admin_ids(organization):
    return list(
        organization.memberships.select_for_update()
        .filter(active=True, role__in=ADMIN_ROLES)
        .values_list("pk", flat=True)
    )


def _audit(organization, request, action, membership, *, metadata=None):
    organization.audit_events.create(
        actor=request.user,
        action=action,
        object_type="membership",
        object_id=str(membership.pk),
        metadata=metadata or {},
    )


@login_required
def members(request):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    memberships = organization.memberships.select_related("user").order_by("user__username")
    return render(
        request,
        "wagvid/members.html",
        {"organization": organization, "memberships": memberships},
    )


@login_required
@transaction.atomic
def member_create(request):
    organization = _organization(request)
    actor_membership = _actor_admin_membership(request, organization)
    if actor_membership is None:
        return HttpResponseForbidden()
    form = MembershipCreateForm(request.POST or None, actor_membership=actor_membership)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user_lookup"]
        role = form.cleaned_data["role"]
        Membership.objects.select_for_update().filter(organization=organization, user=user).first()
        membership, created = Membership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": role, "active": True},
        )
        if not created:
            form.add_error("user_lookup", "Brugeren er allerede medlem af denne organisation.")
        else:
            _audit(
                organization,
                request,
                "membership.created",
                membership,
                metadata={"user_id": user.pk, "role": role},
            )
            messages.success(
                request,
                f"{user.get_username()} er tilføjet som {membership.get_role_display()}.",
            )
            return redirect("members")
    return render(
        request,
        "wagvid/member_form.html",
        {"organization": organization, "title": "Tilføj eksisterende bruger", "form": form},
    )


@login_required
@transaction.atomic
def member_edit(request, membership_id):
    organization = _organization(request)
    actor_membership = _actor_admin_membership(request, organization)
    if actor_membership is None:
        return HttpResponseForbidden()
    membership = get_object_or_404(
        Membership.objects.select_for_update().select_related("user"),
        pk=membership_id,
        organization=organization,
    )
    if (
        membership.role == Membership.Role.SYSTEM_ADMIN
        and actor_membership.role != Membership.Role.SYSTEM_ADMIN
    ):
        return HttpResponseForbidden()

    form = MembershipEditForm(
        request.POST or None,
        instance=membership,
        actor_membership=actor_membership,
    )
    if request.method == "POST" and form.is_valid():
        role = form.cleaned_data["role"]
        active = form.cleaned_data["active"]
        removing_admin = (
            membership.active
            and membership.role in ADMIN_ROLES
            and not (active and role in ADMIN_ROLES)
        )
        active_admin_ids = _locked_active_admin_ids(organization) if removing_admin else []
        if removing_admin and len(active_admin_ids) <= 1:
            form.add_error(None, "Organisationens sidste aktive administrator kan ikke fjernes.")
        else:
            old_role = membership.role
            old_active = membership.active
            updated = form.save()
            _audit(
                organization,
                request,
                "membership.updated",
                updated,
                metadata={
                    "user_id": updated.user_id,
                    "old_role": old_role,
                    "new_role": updated.role,
                    "old_active": old_active,
                    "new_active": updated.active,
                },
            )
            messages.success(request, f"Adgangen for {updated.user.get_username()} er opdateret.")
            return redirect("members")
    return render(
        request,
        "wagvid/member_form.html",
        {
            "organization": organization,
            "title": f"Redigér adgang: {membership.user.get_username()}",
            "form": form,
        },
    )
