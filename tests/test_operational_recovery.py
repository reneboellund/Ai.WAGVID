
import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.backup_recovery import (
    canonical_digest,
    create_backup_plan,
    postgres_backup_command,
    restore_preflight,
    verify_backup,
)
from wagvid_app.master_data import archive_gymnast, merge_gymnasts
from wagvid_app.models import (
    AnalysisJob,
    Gymnast,
    Level,
    MaintenanceState,
    MediaAsset,
    Membership,
    Organization,
    SystemBackup,
)
from wagvid_app.upgrade_ops import upgrade_preflight


def admin_context(label="ops"):
    user = User.objects.create_user(label, password="secret")
    organization = Organization.objects.create(name=label, slug=label)
    Membership.objects.create(
        user=user, organization=organization, role=Membership.Role.ORGANIZATION_ADMIN
    )
    level = Level.objects.create(organization=organization, name="Trin 5")
    return user, organization, level


@pytest.mark.django_db
def test_archive_and_merge_preserve_media_and_audit():
    user, organization, level = admin_context()
    source = Gymnast.objects.create(
        organization=organization, display_name="Dublet", license_number="A", level=level
    )
    target = Gymnast.objects.create(
        organization=organization, display_name="Korrekt", license_number="B", level=level
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=source,
        kind=MediaAsset.Kind.TRAINING,
        recorded_at=timezone.now(),
    )
    merge_gymnasts(source.id, target.id, actor=user, reason="Samme licensindehaver")
    source.refresh_from_db()
    media.refresh_from_db()
    assert source.archived_at is not None
    assert media.gymnast == target
    assert organization.audit_events.filter(action="gymnast.merged").exists()

    fresh = Gymnast.objects.create(
        organization=organization, display_name="Sluttet", license_number="C", level=level
    )
    archive_gymnast(fresh.id, actor=user, reason="Ikke længere aktiv")
    fresh.refresh_from_db()
    assert fresh.archived_at is not None


@pytest.mark.django_db
def test_other_organization_admin_cannot_archive():
    user, _, _ = admin_context("first")
    _, other, level = admin_context("second")
    gymnast = Gymnast.objects.create(
        organization=other, display_name="Beskyttet", license_number="X", level=level
    )
    with pytest.raises(PermissionError):
        archive_gymnast(gymnast.id, actor=user, reason="Forkert organisation")


@pytest.mark.django_db
def test_backup_manifest_has_references_not_secrets_and_verifies():
    user, _, _ = admin_context("backup")
    backup = create_backup_plan(
        requested_by=user,
        purpose=SystemBackup.Purpose.MANUAL,
        destination="offline:test",
        release="0.1",
        git_sha="a" * 40,
    )
    assert backup.manifest["secret_values_included"] is False
    assert backup.manifest["media_bytes_included"] is False
    assert canonical_digest(backup.manifest) == backup.manifest_sha256
    verify_backup(backup.id, database_sha256="b" * 64, actor=user)
    backup.refresh_from_db()
    assert backup.state == SystemBackup.State.VERIFIED
    assert restore_preflight(backup, available_secret_references=set())["activation_allowed"]


def test_pg_dump_contract_does_not_put_password_in_argv():
    command = postgres_backup_command(output_path="safe/database.dump")
    assert command.argv[0] == "pg_dump"
    assert "PGPASSWORD" in command.required_environment
    assert not any("password=" in value.lower() for value in command.argv)


@pytest.mark.django_db
def test_upgrade_preflight_requires_verified_backup():
    result = upgrade_preflight(
        target_manifest={
            "version": "0.1",
            "migration_heads": ["wagvid_app.0014_backup_upgrade_review_admin"],
            "rollback": {"code_only": True},
        }
    )
    assert not result["ready"]
    assert "recent-verified-backup-required" in result["blockers"]


@pytest.mark.django_db
def test_maintenance_blocks_writes_but_keeps_health_available(client):
    user, organization, level = admin_context("maintenance")
    client.force_login(user)
    MaintenanceState.objects.create(active=True, read_only=True, reason="Opgradering")
    response = client.post(
        reverse("gymnast-create"),
        {
            "display_name": "Test",
            "license_number": "T-1",
            "discipline": "WAG",
            "level": level.id,
        },
    )
    assert response.status_code == 503
    assert response.json()["error"] == "maintenance-read-only"
    assert client.get(reverse("health")).status_code == 200
    assert not organization.gymnasts.exists()


@pytest.mark.django_db
def test_review_inbox_is_scoped_and_assignable(client):
    user, organization, level = admin_context("review")
    reviewer = User.objects.create_user("judge", password="secret")
    Membership.objects.create(
        user=reviewer, organization=organization, role=Membership.Role.REVIEWER
    )
    gymnast = Gymnast.objects.create(
        organization=organization, display_name="Ada", license_number="R-1", level=level
    )
    media = MediaAsset.objects.create(
        organization=organization,
        gymnast=gymnast,
        kind=MediaAsset.Kind.TRAINING,
        recorded_at=timezone.now(),
    )
    job = AnalysisJob.objects.create(
        organization=organization,
        media=media,
        state=AnalysisJob.State.NEEDS_REVIEW,
        scope="full",
        rulepack_id="wag-test",
        model_profile="baseline",
        review_reason="score-deviation",
        review_priority=9,
    )
    client.force_login(user)
    inbox = client.get(reverse("review-inbox"), {"reason": "score-deviation"})
    assert inbox.status_code == 200
    assert str(job.id) in inbox.content.decode()
    response = client.post(
        reverse("review-assign", args=[job.id]), {"assignee_id": reviewer.id}, follow=True
    )
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.review_assignee == reviewer
    assert organization.audit_events.filter(action="analysis.review-assigned").exists()
