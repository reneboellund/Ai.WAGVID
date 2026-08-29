import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import Membership, Organization


@pytest.mark.django_db
def test_org_admin_can_add_existing_user_and_audit(client):
    admin = User.objects.create_user("access-admin", password="secret")
    target = User.objects.create_user("coach-user", email="coach@example.test", password="secret")
    org = Organization.objects.create(name="Access Club", slug="access-club")
    Membership.objects.create(
        user=admin,
        organization=org,
        role=Membership.Role.ORGANIZATION_ADMIN,
    )
    client.force_login(admin)

    response = client.post(
        reverse("member-create"),
        {"user_lookup": "coach@example.test", "role": Membership.Role.COACH},
    )
    assert response.status_code == 302
    membership = Membership.objects.get(organization=org, user=target)
    assert membership.role == Membership.Role.COACH
    event = org.audit_events.get(action="membership.created")
    assert event.metadata["user_id"] == target.id
    assert event.metadata["role"] == Membership.Role.COACH


@pytest.mark.django_db
def test_last_active_admin_cannot_be_deactivated_or_demoted(client):
    admin = User.objects.create_user("only-admin", password="secret")
    org = Organization.objects.create(name="Only Admin Club", slug="only-admin-club")
    membership = Membership.objects.create(
        user=admin,
        organization=org,
        role=Membership.Role.ORGANIZATION_ADMIN,
    )
    client.force_login(admin)

    response = client.post(
        reverse("member-edit", args=[membership.id]),
        {"role": Membership.Role.VIEWER},
    )
    assert response.status_code == 200
    assert "sidste aktive administrator" in response.content.decode()
    membership.refresh_from_db()
    assert membership.role == Membership.Role.ORGANIZATION_ADMIN
    assert membership.active is True


@pytest.mark.django_db
def test_admin_can_change_role_when_another_admin_remains(client):
    first = User.objects.create_user("first-admin", password="secret")
    second = User.objects.create_user("second-admin", password="secret")
    org = Organization.objects.create(name="Two Admin Club", slug="two-admin-club")
    first_membership = Membership.objects.create(
        user=first,
        organization=org,
        role=Membership.Role.ORGANIZATION_ADMIN,
    )
    Membership.objects.create(
        user=second,
        organization=org,
        role=Membership.Role.ORGANIZATION_ADMIN,
    )
    client.force_login(first)

    response = client.post(
        reverse("member-edit", args=[first_membership.id]),
        {"role": Membership.Role.REVIEWER, "active": "on"},
    )
    assert response.status_code == 302
    first_membership.refresh_from_db()
    assert first_membership.role == Membership.Role.REVIEWER
    assert org.audit_events.filter(action="membership.updated").exists()


@pytest.mark.django_db
def test_non_admin_cannot_manage_memberships(client):
    viewer = User.objects.create_user("access-viewer", password="secret")
    org = Organization.objects.create(name="Read Access Club", slug="read-access-club")
    Membership.objects.create(user=viewer, organization=org, role=Membership.Role.VIEWER)
    client.force_login(viewer)

    assert client.get(reverse("members")).status_code == 403
    assert client.get(reverse("member-create")).status_code == 403


@pytest.mark.django_db
def test_member_edit_is_organization_scoped(client):
    admin = User.objects.create_user("scope-admin", password="secret")
    other_user = User.objects.create_user("other-member", password="secret")
    org = Organization.objects.create(name="Scope Club", slug="scope-club")
    other = Organization.objects.create(name="Other Access", slug="other-access")
    Membership.objects.create(
        user=admin,
        organization=org,
        role=Membership.Role.ORGANIZATION_ADMIN,
    )
    other_membership = Membership.objects.create(
        user=other_user,
        organization=other,
        role=Membership.Role.VIEWER,
    )
    client.force_login(admin)

    assert client.get(reverse("member-edit", args=[other_membership.id])).status_code == 404
