import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.models import Event, Gymnast, Level, MediaAsset, Membership, Organization, Routine


def _merge_fixture():
    user = User.objects.create_user("merge-admin", password="secret")
    org = Organization.objects.create(name="Merge Club", slug="merge-club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.ORGANIZATION_ADMIN)
    level = Level.objects.create(organization=org, name="Junior")
    survivor = Gymnast.objects.create(
        organization=org,
        display_name="Canonical Athlete",
        license_number="CAN-1",
        discipline=Gymnast.Discipline.WAG,
        level=level,
    )
    duplicate = Gymnast.objects.create(
        organization=org,
        display_name="Duplicate Athlete",
        license_number="DUP-1",
        discipline=Gymnast.Discipline.WAG,
        level=level,
        kiga_id="KIGA-DUP",
    )
    event = Event.objects.create(
        organization=org,
        name="Merge Test",
        kind=Event.Kind.TRAINING,
        starts_at=timezone.now(),
    )
    routine = Routine.objects.create(
        organization=org,
        event=event,
        gymnast=duplicate,
        apparatus=Routine.Apparatus.BEAM,
        rulepack_id="wag-test",
    )
    media = MediaAsset.objects.create(
        organization=org,
        gymnast=duplicate,
        routine=routine,
        kind=MediaAsset.Kind.ROUTINE,
        recorded_at=timezone.now(),
    )
    return user, org, level, survivor, duplicate, routine, media


@pytest.mark.django_db
def test_admin_merge_moves_history_archives_duplicate_and_audits(client):
    user, org, _level, survivor, duplicate, routine, media = _merge_fixture()
    client.force_login(user)

    response = client.post(
        reverse("gymnast-merge", args=[duplicate.id]),
        {"survivor": str(survivor.id), "reason": "Imported duplicate profile"},
    )
    assert response.status_code == 302

    survivor.refresh_from_db()
    duplicate.refresh_from_db()
    routine.refresh_from_db()
    media.refresh_from_db()
    assert duplicate.archived_at is not None
    assert routine.gymnast_id == survivor.id
    assert media.gymnast_id == survivor.id
    assert survivor.kiga_id == "KIGA-DUP"

    event = org.audit_events.get(action="gymnast.merged")
    assert event.object_id == str(survivor.id)
    assert event.reason == "Imported duplicate profile"
    assert event.metadata["duplicate_id"] == str(duplicate.id)
    assert event.metadata["routines_moved"] == 1
    assert event.metadata["media_moved"] == 1
    assert event.metadata["kiga_id_transferred"] is True
    assert org.audit_events.filter(
        action="gymnast.merged-into", object_id=str(duplicate.id)
    ).exists()


@pytest.mark.django_db
def test_merge_blocks_conflicting_kiga_ids_without_partial_updates(client):
    user, _org, _level, survivor, duplicate, routine, media = _merge_fixture()
    survivor.kiga_id = "KIGA-CANONICAL"
    survivor.save(update_fields=["kiga_id", "updated_at"])
    client.force_login(user)

    response = client.post(
        reverse("gymnast-merge", args=[duplicate.id]),
        {"survivor": str(survivor.id), "reason": "Suspected duplicate"},
    )
    assert response.status_code == 200
    assert "forskellige KIGA-ID" in response.content.decode()

    duplicate.refresh_from_db()
    routine.refresh_from_db()
    media.refresh_from_db()
    assert duplicate.archived_at is None
    assert routine.gymnast_id == duplicate.id
    assert media.gymnast_id == duplicate.id


@pytest.mark.django_db
def test_merge_survivor_is_scoped_to_active_organization(client):
    user, _org, _level, _survivor, duplicate, _routine, _media = _merge_fixture()
    other = Organization.objects.create(name="Other Merge Club", slug="other-merge-club")
    other_level = Level.objects.create(organization=other, name="Youth")
    other_survivor = Gymnast.objects.create(
        organization=other,
        display_name="Other Athlete",
        license_number="OTHER-1",
        discipline=Gymnast.Discipline.WAG,
        level=other_level,
    )
    client.force_login(user)

    response = client.post(
        reverse("gymnast-merge", args=[duplicate.id]),
        {"survivor": str(other_survivor.id), "reason": "Invalid cross-org merge"},
    )
    assert response.status_code == 200
    duplicate.refresh_from_db()
    assert duplicate.archived_at is None


@pytest.mark.django_db
def test_operator_cannot_open_or_submit_merge(client):
    _admin, org, level, _survivor, duplicate, _routine, _media = _merge_fixture()
    operator = User.objects.create_user("merge-operator", password="secret")
    Membership.objects.create(user=operator, organization=org, role=Membership.Role.OPERATOR)
    target = Gymnast.objects.create(
        organization=org,
        display_name="Target Athlete",
        license_number="TARGET-1",
        discipline=Gymnast.Discipline.WAG,
        level=level,
    )
    client.force_login(operator)

    assert client.get(reverse("gymnast-merge", args=[duplicate.id])).status_code == 403
    assert client.post(
        reverse("gymnast-merge", args=[duplicate.id]),
        {"survivor": str(target.id), "reason": "Not allowed"},
    ).status_code == 403
