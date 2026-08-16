import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from wagvid_app.models import AuditEvent, ExchangeJob, Gymnast, Level, Membership, Organization


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
    Gymnast.objects.create(
        organization=own, display_name="Own Gymnast", license_number="OWN-1", level=own_level
    )
    Gymnast.objects.create(
        organization=other,
        display_name="Other Gymnast",
        license_number="OTHER-1",
        level=other_level,
    )
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
    event = AuditEvent.objects.create(
        organization=org, action="test", object_type="system", object_id="1"
    )
    event.reason = "changed"
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()


@pytest.mark.django_db
def test_admin_can_preview_commit_and_export_gymnasts(client):
    user = User.objects.create_user("admin", password="secret")
    org = Organization.objects.create(name="Club", slug="club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.ORGANIZATION_ADMIN)
    Level.objects.create(organization=org, name="Trin 3")
    client.force_login(user)
    upload = SimpleUploadedFile(
        "gymnasts.csv",
        b"name,license_number,level,kiga_id\nAda,DK-7,Trin 3,K-7\n",
        content_type="text/csv",
    )
    preview = client.post(reverse("exchange"), {"csv_file": upload})
    assert preview.status_code == 200
    assert "1 gyldige" in preview.content.decode()
    committed = client.post(reverse("gymnast-import-commit"), follow=True)
    assert committed.status_code == 200
    assert org.gymnasts.filter(license_number="DK-7").exists()
    assert ExchangeJob.objects.filter(state=ExchangeJob.State.COMPLETED).exists()
    assert org.audit_events.filter(action="gymnasts.imported").exists()
    exported = client.get(reverse("gymnast-export"))
    assert exported.status_code == 200
    assert "DK-7" in exported.content.decode("utf-8-sig")


@pytest.mark.django_db
def test_admin_can_download_scoped_import_error_report(client):
    user = User.objects.create_user("error-admin", password="secret")
    org = Organization.objects.create(name="Error Club", slug="error-club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.ORGANIZATION_ADMIN)
    Level.objects.create(organization=org, name="Trin 3")
    client.force_login(user)
    upload = SimpleUploadedFile(
        "gymnasts.csv", b"name,license_number,level\n,DK-7,Trin 3\n", content_type="text/csv"
    )
    preview = client.post(reverse("exchange"), {"csv_file": upload})
    assert "Download fejlrapport" in preview.content.decode()
    report = client.get(reverse("gymnast-import-errors"))
    assert report.status_code == 200
    assert "Name is required" in report.content.decode()
    assert len(report["X-WAGVID-Preview-Digest"]) == 64


@pytest.mark.django_db
def test_operator_cannot_import_gymnasts(client):
    user = User.objects.create_user("limited", password="secret")
    org = Organization.objects.create(name="Club", slug="club")
    Membership.objects.create(user=user, organization=org, role=Membership.Role.OPERATOR)
    client.force_login(user)
    upload = SimpleUploadedFile("gymnasts.csv", b"name,license_number,level\n")
    assert client.post(reverse("exchange"), {"csv_file": upload}).status_code == 403
