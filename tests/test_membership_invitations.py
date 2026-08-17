import hashlib
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from wagvid_app.invitation_operations import (
    InvitationError,
    accept_invitation,
    create_invitation,
    lookup_invitation,
    revoke_invitation,
)
from wagvid_app.membership_invitations import MembershipInvitation
from wagvid_app.models import Membership, Organization

User = get_user_model()


def user(username, email):
    return User.objects.create_user(username=username, email=email, password="very-secure-test-password")


def organization_with_admin(*, role=Membership.Role.SYSTEM_ADMIN):
    organization = Organization.objects.create(name="Invite Club", slug=f"invite-club-{role}")
    admin = user(f"admin-{role}", f"admin-{role}@example.test")
    Membership.objects.create(organization=organization, user=admin, role=role, active=True)
    return organization, admin


@pytest.mark.django_db
def test_invitation_persists_only_token_hash_and_audits_without_plaintext_token():
    organization, admin = organization_with_admin()
    grant = create_invitation(
        organization,
        actor=admin,
        email="New.Member@Example.Test",
        role=Membership.Role.COACH,
    )
    invitation = MembershipInvitation.objects.get(pk=grant.invitation.pk)
    assert invitation.email == "new.member@example.test"
    assert invitation.token_hash == hashlib.sha256(grant.token.encode()).hexdigest()
    assert grant.token not in invitation.token_hash
    event = organization.audit_events.get(action="membership.invitation.created")
    assert grant.token not in str(event.metadata)
    assert event.metadata["role"] == Membership.Role.COACH


@pytest.mark.django_db
def test_new_invitation_supersedes_previous_pending_token_for_same_email():
    organization, admin = organization_with_admin()
    first = create_invitation(
        organization, actor=admin, email="coach@example.test", role=Membership.Role.COACH
    )
    second = create_invitation(
        organization, actor=admin, email="coach@example.test", role=Membership.Role.REVIEWER
    )
    assert lookup_invitation(first.token).reason == "revoked"
    assert lookup_invitation(second.token).pending
    assert MembershipInvitation.objects.get(pk=first.invitation.pk).revoked_at is not None


@pytest.mark.django_db
def test_organization_admin_cannot_invite_system_admin():
    organization, admin = organization_with_admin(role=Membership.Role.ORGANIZATION_ADMIN)
    with pytest.raises(PermissionDenied):
        create_invitation(
            organization,
            actor=admin,
            email="root@example.test",
            role=Membership.Role.SYSTEM_ADMIN,
        )


@pytest.mark.django_db
def test_invitation_acceptance_is_email_bound_single_use_and_audited():
    organization, admin = organization_with_admin()
    grant = create_invitation(
        organization, actor=admin, email="coach@example.test", role=Membership.Role.COACH
    )
    wrong = user("wrong", "other@example.test")
    with pytest.raises(PermissionDenied):
        accept_invitation(grant.token, user=wrong)

    invited = user("coach", "COACH@example.test")
    membership = accept_invitation(grant.token, user=invited)
    assert membership.organization == organization
    assert membership.role == Membership.Role.COACH
    assert membership.active
    assert MembershipInvitation.objects.get(pk=grant.invitation.pk).accepted_by == invited
    with pytest.raises(InvitationError, match="accepted"):
        accept_invitation(grant.token, user=invited)
    event = organization.audit_events.get(action="membership.invitation.accepted")
    assert event.actor == invited
    assert event.metadata["membership_id"] == membership.pk


@pytest.mark.django_db
def test_revoked_and_expired_invitations_cannot_be_accepted():
    organization, admin = organization_with_admin()
    invited = user("coach", "coach@example.test")
    grant = create_invitation(
        organization, actor=admin, email=invited.email, role=Membership.Role.COACH
    )
    revoke_invitation(grant.invitation.pk, organization=organization, actor=admin)
    with pytest.raises(InvitationError, match="revoked"):
        accept_invitation(grant.token, user=invited)

    expired = create_invitation(
        organization, actor=admin, email="late@example.test", role=Membership.Role.VIEWER
    )
    MembershipInvitation.objects.filter(pk=expired.invitation.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(InvitationError, match="expired"):
        accept_invitation(expired.token, user=user("late", "late@example.test"))


@pytest.mark.django_db
def test_admin_create_view_shows_raw_link_once_but_list_never_contains_token(client):
    organization, admin = organization_with_admin()
    client.force_login(admin)
    response = client.post(
        reverse("membership-invitation-create"),
        {"email": "new@example.test", "role": Membership.Role.COACH},
    )
    assert response.status_code == 200
    invitation = MembershipInvitation.objects.get(email="new@example.test")
    assert invitation.token_hash
    body = response.content.decode()
    assert "/invite/" in body

    listing = client.get(reverse("membership-invitations"))
    assert listing.status_code == 200
    assert invitation.token_hash not in listing.content.decode()
    assert "new@example.test" in listing.content.decode()


@pytest.mark.django_db
def test_public_invitation_can_create_account_and_membership_atomically(client):
    organization, admin = organization_with_admin()
    grant = create_invitation(
        organization,
        actor=admin,
        email="new.account@example.test",
        role=Membership.Role.REVIEWER,
    )
    response = client.post(
        reverse("membership-invitation-accept", kwargs={"token": grant.token}),
        {
            "username": "new-account",
            "password1": "a-strong-test-password-2026",
            "password2": "a-strong-test-password-2026",
        },
    )
    assert response.status_code == 302
    created = User.objects.get(username="new-account")
    assert created.email == "new.account@example.test"
    membership = Membership.objects.get(organization=organization, user=created)
    assert membership.role == Membership.Role.REVIEWER
    assert membership.active
    assert MembershipInvitation.objects.get(pk=grant.invitation.pk).accepted_by == created


@pytest.mark.django_db
def test_existing_account_invitation_requires_login_and_preserves_next_link(client):
    organization, admin = organization_with_admin()
    existing = user("existing", "existing@example.test")
    grant = create_invitation(
        organization, actor=admin, email=existing.email, role=Membership.Role.VIEWER
    )
    response = client.get(reverse("membership-invitation-accept", kwargs={"token": grant.token}))
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("login") in body
    assert "next=" in body
    assert User.objects.filter(email__iexact=existing.email).count() == 1


@pytest.mark.django_db
def test_org_admin_cannot_escalate_existing_user_to_system_admin_through_legacy_member_form(client):
    organization, admin = organization_with_admin(role=Membership.Role.ORGANIZATION_ADMIN)
    target = user("target", "target@example.test")
    client.force_login(admin)
    response = client.post(
        reverse("member-create"),
        {"user_lookup": target.username, "role": Membership.Role.SYSTEM_ADMIN},
    )
    assert response.status_code == 200
    assert not Membership.objects.filter(organization=organization, user=target).exists()
    allowed = {value for value, _label in response.context["form"].fields["role"].choices}
    assert Membership.Role.SYSTEM_ADMIN not in allowed


@pytest.mark.django_db
def test_org_admin_cannot_edit_existing_system_admin(client):
    organization, org_admin = organization_with_admin(role=Membership.Role.ORGANIZATION_ADMIN)
    system_admin = user("system-admin", "system@example.test")
    target_membership = Membership.objects.create(
        organization=organization,
        user=system_admin,
        role=Membership.Role.SYSTEM_ADMIN,
        active=True,
    )
    client.force_login(org_admin)
    response = client.post(
        reverse("member-edit", kwargs={"membership_id": target_membership.pk}),
        {"role": Membership.Role.VIEWER, "active": "on"},
    )
    assert response.status_code == 403
    target_membership.refresh_from_db()
    assert target_membership.role == Membership.Role.SYSTEM_ADMIN
