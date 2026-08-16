import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wagvid_app.forms import GymnastForm
from wagvid_app.models import Gymnast, Level, Membership, Organization


def _admin_fixture():
    user = User.objects.create_user("master-admin", password="secret")
    org = Organization.objects.create(name="Master Club", slug="master-club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.ORGANIZATION_ADMIN)
    level = Level.objects.create(organization=org, name="Trin 4")
    gymnast = Gymnast.objects.create(
        organization=org,
        display_name="Ada Example",
        license_number="DK-100",
        level=level,
    )
    return user, org, level, gymnast


@pytest.mark.django_db
def test_admin_can_edit_gymnast_and_audit_changed_fields(client):
    user, org, level, gymnast = _admin_fixture()
    client.force_login(user)
    response = client.post(
        reverse("gymnast-edit", args=[gymnast.id]),
        {
            "display_name": "Ada Updated",
            "license_number": gymnast.license_number,
            "discipline": Gymnast.Discipline.WAG,
            "level": str(level.id),
            "kiga_id": "KIGA-100",
        },
    )
    assert response.status_code == 302
    gymnast.refresh_from_db()
    assert gymnast.display_name == "Ada Updated"
    event = org.audit_events.get(action="gymnast.updated")
    assert "display_name" in event.metadata["changed_fields"]
    assert "kiga_id" in event.metadata["changed_fields"]


@pytest.mark.django_db
def test_inactive_current_level_remains_valid_when_editing_gymnast():
    _user, org, level, gymnast = _admin_fixture()
    level.active = False
    level.save(update_fields=["active", "updated_at"])
    form = GymnastForm(instance=gymnast, organization=org)
    assert level in form.fields["level"].queryset


@pytest.mark.django_db
def test_archive_and_restore_preserve_gymnast_record(client):
    user, org, _level, gymnast = _admin_fixture()
    client.force_login(user)
    archived = client.post(
        reverse("gymnast-archive", args=[gymnast.id]),
        {"reason": "Season ended"},
    )
    assert archived.status_code == 302
    gymnast.refresh_from_db()
    assert gymnast.archived_at is not None
    assert org.audit_events.filter(action="gymnast.archived", object_id=str(gymnast.id)).exists()
    active_page = client.get(reverse("gymnasts")).content.decode()
    assert "0 profiler" in active_page
    archived_page = client.get(reverse("gymnasts-archived")).content.decode()
    assert "Ada Example" in archived_page

    restored = client.post(reverse("gymnast-restore", args=[gymnast.id]))
    assert restored.status_code == 302
    gymnast.refresh_from_db()
    assert gymnast.archived_at is None
    assert org.audit_events.filter(action="gymnast.restored", object_id=str(gymnast.id)).exists()


@pytest.mark.django_db
def test_operator_cannot_mutate_master_data(client):
    user = User.objects.create_user("master-operator", password="secret")
    org = Organization.objects.create(name="Operator Club", slug="operator-club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OPERATOR)
    level = Level.objects.create(organization=org, name="Youth")
    gymnast = Gymnast.objects.create(
        organization=org, display_name="Read Only", license_number="RO-1", level=level
    )
    client.force_login(user)
    assert client.get(reverse("gymnast-edit", args=[gymnast.id])).status_code == 403
    assert client.post(reverse("gymnast-archive", args=[gymnast.id])).status_code == 403
    assert client.get(reverse("level-create")).status_code == 403
    assert client.post(reverse("level-archive", args=[level.id])).status_code == 403


@pytest.mark.django_db
def test_master_data_routes_are_organization_scoped(client):
    user, _org, _level, _gymnast = _admin_fixture()
    other = Organization.objects.create(name="Other Club", slug="other-master-club")
    other_level = Level.objects.create(organization=other, name="Other Level")
    other_gymnast = Gymnast.objects.create(
        organization=other,
        display_name="Other Gymnast",
        license_number="OTHER-1",
        level=other_level,
    )
    client.force_login(user)
    assert client.get(reverse("gymnast-edit", args=[other_gymnast.id])).status_code == 404
    assert client.get(reverse("level-edit", args=[other_level.id])).status_code == 404


@pytest.mark.django_db
def test_admin_can_create_edit_and_deactivate_level(client):
    user, org, _level, _gymnast = _admin_fixture()
    client.force_login(user)
    created = client.post(reverse("level-create"), {"name": "Junior", "active": "on"})
    assert created.status_code == 302
    junior = org.levels.get(name="Junior")
    assert org.audit_events.filter(action="level.created", object_id=str(junior.id)).exists()

    duplicate = client.post(reverse("level-create"), {"name": "junior", "active": "on"})
    assert duplicate.status_code == 200
    assert "allerede et niveau" in duplicate.content.decode()

    edited = client.post(
        reverse("level-edit", args=[junior.id]), {"name": "Junior DMC", "active": "on"}
    )
    assert edited.status_code == 302
    junior.refresh_from_db()
    assert junior.name == "Junior DMC"
    assert org.audit_events.filter(action="level.updated", object_id=str(junior.id)).exists()

    archived = client.post(reverse("level-archive", args=[junior.id]))
    assert archived.status_code == 302
    junior.refresh_from_db()
    assert junior.active is False
    assert org.audit_events.filter(action="level.archived", object_id=str(junior.id)).exists()
