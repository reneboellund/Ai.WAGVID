import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.models import AuditEvent, Gymnast, Level, Membership, Organization


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_health_and_readiness_are_machine_readable(client):
    assert client.get(reverse("health")).json()["status"] == "ok"
    response = client.get(reverse("readiness"))
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


@pytest.mark.django_db
def test_member_sees_only_own_organization_gymnasts(client):
    user = User.objects.create_user("operator", password="secret")
    own = Organization.objects.create(name="Own", slug="own")
    other = Organization.objects.create(name="Other", slug="other")
    Membership.objects.create(user=user, organization=own, role=Membership.Role.OPERATOR)
    own_level = Level.objects.create(organization=own, name="Trin 5")
    other_level = Level.objects.create(organization=other, name="Trin 6")
    Gymnast.objects.create(organization=own, display_name="Own Gymnast", license_number="OWN-1", level=own_level)
    Gymnast.objects.create(organization=other, display_name="Other Gymnast", license_number="OTHER-1", level=other_level)
    client.force_login(user)
    response = client.get(reverse("gymnasts"))
    body = response.content.decode()
    assert "Own Gymnast" in body
    assert "Other Gymnast" not in body


@pytest.mark.django_db
def test_operator_cannot_create_gymnast(client):
    user = User.objects.create_user("operator", password="secret")
    org = Organization.objects.create(name="Club", slug="club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OPERATOR)
    client.force_login(user)
    assert client.get(reverse("gymnast-create")).status_code == 403


@pytest.mark.django_db
def test_audit_event_is_append_only():
    org = Organization.objects.create(name="Club", slug="club")
    event = AuditEvent.objects.create(organization=org, action="test", object_type="system", object_id="1")
    event.reason = "changed"
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()
