"""Single-use, auditable organization membership invitation operations."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .membership_invitations import MembershipInvitation
from .models import Membership, Organization

User = get_user_model()
MIN_TTL = timedelta(minutes=5)
MAX_TTL = timedelta(days=7)
DEFAULT_TTL = timedelta(hours=48)


class InvitationError(ValueError):
    pass


@dataclass(frozen=True)
class InvitationGrant:
    invitation: MembershipInvitation
    token: str


@dataclass(frozen=True)
class InvitationState:
    invitation: MembershipInvitation
    pending: bool
    reason: str | None


def normalize_email(value: str) -> str:
    normalized = User.objects.normalize_email((value or "").strip()).casefold()
    if not normalized or "@" not in normalized:
        raise ValidationError("En gyldig e-mailadresse er påkrævet.")
    return normalized


def token_hash(raw_token: str) -> str:
    if not raw_token:
        raise InvitationError("Invitation token is required")
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _actor_membership(actor, organization: Organization, *, lock: bool = False) -> Membership:
    query = Membership.objects.filter(
        organization=organization,
        user=actor,
        active=True,
        role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN],
    )
    if lock:
        query = query.select_for_update()
    membership = query.first()
    if membership is None:
        raise PermissionDenied("Du må ikke administrere invitationer for denne organisation.")
    return membership


def _authorize_role(actor_membership: Membership, role: str) -> None:
    if role not in Membership.Role.values:
        raise InvitationError("Unknown membership role")
    if role == Membership.Role.SYSTEM_ADMIN and actor_membership.role != Membership.Role.SYSTEM_ADMIN:
        raise PermissionDenied("Kun en systemadministrator kan invitere en systemadministrator.")


def invitation_state(invitation: MembershipInvitation, *, now=None) -> InvitationState:
    current = now or timezone.now()
    if invitation.accepted_at is not None:
        return InvitationState(invitation, False, "accepted")
    if invitation.revoked_at is not None:
        return InvitationState(invitation, False, "revoked")
    if invitation.expires_at <= current:
        return InvitationState(invitation, False, "expired")
    return InvitationState(invitation, True, None)


def lookup_invitation(raw_token: str, *, now=None) -> InvitationState:
    try:
        invitation = MembershipInvitation.objects.select_related("organization", "created_by").get(
            token_hash=token_hash(raw_token)
        )
    except MembershipInvitation.DoesNotExist as error:
        raise InvitationError("Invitationen findes ikke eller er ugyldig.") from error
    return invitation_state(invitation, now=now)


@transaction.atomic
def create_invitation(
    organization: Organization,
    *,
    actor,
    email: str,
    role: str,
    ttl: timedelta = DEFAULT_TTL,
) -> InvitationGrant:
    actor_membership = _actor_membership(actor, organization, lock=True)
    _authorize_role(actor_membership, role)
    if ttl < MIN_TTL or ttl > MAX_TTL:
        raise InvitationError("Invitation TTL must be between 5 minutes and 7 days")
    normalized = normalize_email(email)
    now = timezone.now()

    # An already-active member needs role administration, not a second invitation path.
    active_user_ids = User.objects.filter(email__iexact=normalized).values_list("pk", flat=True)
    if Membership.objects.filter(
        organization=organization, user_id__in=active_user_ids, active=True
    ).exists():
        raise InvitationError("Brugeren er allerede aktivt medlem af organisationen.")

    pending = MembershipInvitation.objects.select_for_update().filter(
        organization=organization,
        email__iexact=normalized,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=now,
    )
    revoked_count = pending.update(revoked_at=now)

    raw_token = secrets.token_urlsafe(32)
    invitation = MembershipInvitation.objects.create(
        organization=organization,
        email=normalized,
        role=role,
        token_hash=token_hash(raw_token),
        expires_at=now + ttl,
        created_by=actor,
    )
    organization.audit_events.create(
        actor=actor,
        action="membership.invitation.created",
        object_type="membership-invitation",
        object_id=str(invitation.pk),
        metadata={
            "email": normalized,
            "role": role,
            "expires_at": invitation.expires_at.isoformat(),
            "superseded_pending_invitations": revoked_count,
        },
    )
    return InvitationGrant(invitation, raw_token)


@transaction.atomic
def revoke_invitation(invitation_id, *, organization: Organization, actor) -> MembershipInvitation:
    actor_membership = _actor_membership(actor, organization, lock=True)
    invitation = MembershipInvitation.objects.select_for_update().get(
        pk=invitation_id, organization=organization
    )
    _authorize_role(actor_membership, invitation.role)
    state = invitation_state(invitation)
    if not state.pending:
        raise InvitationError(f"Invitationen kan ikke tilbagekaldes: {state.reason}.")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    organization.audit_events.create(
        actor=actor,
        action="membership.invitation.revoked",
        object_type="membership-invitation",
        object_id=str(invitation.pk),
        metadata={"email": invitation.email, "role": invitation.role},
    )
    return invitation


@transaction.atomic
def accept_invitation(raw_token: str, *, user) -> Membership:
    try:
        invitation = (
            MembershipInvitation.objects.select_for_update()
            .select_related("organization")
            .get(token_hash=token_hash(raw_token))
        )
    except MembershipInvitation.DoesNotExist as error:
        raise InvitationError("Invitationen findes ikke eller er ugyldig.") from error

    state = invitation_state(invitation)
    if not state.pending:
        raise InvitationError(f"Invitationen kan ikke bruges: {state.reason}.")
    user_email = normalize_email(getattr(user, "email", ""))
    if user_email != invitation.email.casefold():
        raise PermissionDenied("Invitationens e-mail matcher ikke den indloggede bruger.")

    # Serialize a possible concurrent accept/reactivation for this organization/user pair.
    existing = (
        Membership.objects.select_for_update()
        .filter(organization=invitation.organization, user=user)
        .first()
    )
    if existing is None:
        membership = Membership.objects.create(
            organization=invitation.organization,
            user=user,
            role=invitation.role,
            active=True,
        )
        previous = None
    else:
        previous = {"role": existing.role, "active": existing.active}
        # An invitation may never silently downgrade an existing active system administrator.
        if existing.active and existing.role == Membership.Role.SYSTEM_ADMIN:
            raise InvitationError("Systemadministrator-adgang skal ændres via rolleadministrationen.")
        existing.role = invitation.role
        existing.active = True
        existing.save(update_fields=["role", "active", "updated_at"])
        membership = existing

    accepted_at = timezone.now()
    invitation.accepted_at = accepted_at
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    invitation.organization.audit_events.create(
        actor=user,
        action="membership.invitation.accepted",
        object_type="membership-invitation",
        object_id=str(invitation.pk),
        metadata={
            "email": invitation.email,
            "role": invitation.role,
            "membership_id": membership.pk,
            "previous_membership": previous,
        },
    )
    return membership
