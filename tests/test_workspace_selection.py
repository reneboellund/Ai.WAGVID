import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import Membership, Organization
from wagvid_app.organization_context import SESSION_KEY


@pytest.mark.django_db
def test_user_can_switch_between_active_organization_memberships(client):
    user = User.objects.create_user("multi-org", password="secret")
    first = Organization.objects.create(name="Alpha Club", slug="alpha-club")
    second = Organization.objects.create(name="Beta Club", slug="beta-club")
    Membership.objects.create(user=user, organization=first, role=Membership.Role.VIEWER)
    Membership.objects.create(user=user, organization=second, role=Membership.Role.COACH)
    client.force_login(user)

    initial = client.get(reverse("dashboard"))
    assert initial.status_code == 200
    assert "Alpha Club" in initial.content.decode()

    switched = client.post(reverse("workspace-switch", args=[second.id]))
    assert switched.status_code == 302
    assert client.session[SESSION_KEY] == str(second.id)

    dashboard = client.get(reverse("dashboard"))
    assert dashboard.status_code == 200
    assert "Beta Club" in dashboard.content.decode()
    event = second.audit_events.get(action="workspace.selected")
    assert event.metadata["previous_organization_id"] == str(first.id)


@pytest.mark.django_db
def test_workspace_switch_rejects_organization_without_membership(client):
    user = User.objects.create_user("scoped-workspace", password="secret")
    allowed = Organization.objects.create(name="Allowed Club", slug="allowed-club")
    forbidden = Organization.objects.create(name="Forbidden Club", slug="forbidden-club")
    Membership.objects.create(user=user, organization=allowed, role=Membership.Role.VIEWER)
    client.force_login(user)

    response = client.post(reverse("workspace-switch", args=[forbidden.id]))
    assert response.status_code == 403
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_inactive_membership_cannot_remain_selected(client):
    user = User.objects.create_user("inactive-workspace", password="secret")
    active_org = Organization.objects.create(name="Active Club", slug="active-club")
    inactive_org = Organization.objects.create(name="Old Club", slug="old-club")
    Membership.objects.create(user=user, organization=active_org, role=Membership.Role.VIEWER)
    Membership.objects.create(
        user=user,
        organization=inactive_org,
        role=Membership.Role.VIEWER,
        active=False,
    )
    client.force_login(user)
    session = client.session
    session[SESSION_KEY] = str(inactive_org.id)
    session.save()

    response = client.get(reverse("dashboard"))
    assert response.status_code == 200
    assert "Active Club" in response.content.decode()
    assert SESSION_KEY not in client.session


@pytest.mark.django_db
def test_workspace_list_only_contains_active_access(client):
    user = User.objects.create_user("workspace-list", password="secret")
    visible = Organization.objects.create(name="Visible Club", slug="visible-club")
    hidden = Organization.objects.create(name="Hidden Club", slug="hidden-club")
    Membership.objects.create(user=user, organization=visible, role=Membership.Role.COACH)
    Membership.objects.create(user=user, organization=hidden, role=Membership.Role.COACH, active=False)
    client.force_login(user)

    response = client.get(reverse("workspaces"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Visible Club" in content
    assert "Hidden Club" not in content
