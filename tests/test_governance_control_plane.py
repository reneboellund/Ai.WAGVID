import hashlib

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.governance import (
    accept_invitation,
    change_member_role,
    create_configuration_revision,
    create_evidence_share,
    invite_member,
    register_dataset_source,
    revoke_evidence_share,
    validate_evidence_share,
)
from wagvid_app.models import (
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
)


def context(slug="governance", role=Membership.Role.ORGANIZATION_ADMIN):
    user = User.objects.create_user(slug, email=f"{slug}@example.test", password="secret")
    organization = Organization.objects.create(name=slug.title(), slug=slug)
    membership = Membership.objects.create(user=user, organization=organization, role=role)
    return user, organization, membership


@pytest.mark.django_db
def test_invitation_token_is_hashed_single_use_and_email_bound():
    admin, organization, _ = context()
    invitation, token = invite_member(
        organization=organization,
        actor=admin,
        email="reviewer@example.test",
        role=Membership.Role.DOMAIN_REVIEWER,
    )
    assert token not in invitation.token_hash
    assert invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()
    reviewer = User.objects.create_user("reviewer", email="reviewer@example.test")
    accept_invitation(raw_token=token, user=reviewer)
    assert Membership.objects.get(user=reviewer, organization=organization).role == Membership.Role.DOMAIN_REVIEWER
    with pytest.raises(ValueError):
        accept_invitation(raw_token=token, user=reviewer)
    assert organization.audit_events.filter(action="membership.invitation-accepted").exists()


@pytest.mark.django_db
def test_invitation_cannot_create_system_admin():
    admin, organization, _ = context()
    with pytest.raises(ValueError):
        invite_member(organization=organization, actor=admin, email="root@example.test", role=Membership.Role.SYSTEM_ADMIN)


@pytest.mark.django_db
def test_role_change_requires_reason_and_prevents_self_lockout():
    admin, organization, membership = context()
    with pytest.raises(ValueError):
        change_member_role(membership=membership, actor=admin, role=Membership.Role.VIEWER, active=True, reason="")
    with pytest.raises(ValueError):
        change_member_role(membership=membership, actor=admin, role=Membership.Role.VIEWER, active=True, reason="self demotion")
    other = User.objects.create_user("other")
    other_membership = Membership.objects.create(user=other, organization=organization, role=Membership.Role.VIEWER)
    change_member_role(membership=other_membership, actor=admin, role=Membership.Role.ANNOTATOR, active=True, reason="Annotation duty")
    other_membership.refresh_from_db()
    assert other_membership.role == Membership.Role.ANNOTATOR


@pytest.mark.django_db
def test_configuration_freeze_rejects_plain_secrets_and_is_immutable():
    admin, organization, _ = context()
    with pytest.raises(ValueError, match="secret reference"):
        create_configuration_revision(organization=organization, actor=admin, namespace="storage", values={"api_secret": "plaintext"}, reason="unsafe")
    revision = create_configuration_revision(
        organization=organization,
        actor=admin,
        namespace="storage",
        values={"api_secret": "vault:wagvid/storage", "threshold": 0.8},
        reason="production freeze",
        freeze=True,
    )
    assert revision.state == "frozen" and len(revision.digest) == 64
    revision.reason = "silently changed"
    with pytest.raises(ValueError, match="immutable"):
        revision.save()
    successor = create_configuration_revision(organization=organization, actor=admin, namespace="storage", values={"api_secret": "vault:wagvid/storage-v2"}, reason="credential rotation", freeze=True)
    revision.refresh_from_db()
    assert successor.revision == 2 and revision.state == "frozen"


@pytest.mark.django_db
def test_dataset_permissions_are_explicit_pseudonymous_and_immutable():
    admin, organization, _ = context()
    record = register_dataset_source(
        organization=organization,
        actor=admin,
        source_reference="internal://clip/42",
        immutable_digest="a" * 64,
        rights_reference="approval-2026-42",
        analysis_allowed=True,
        retention_allowed=True,
        training_allowed=False,
        export_allowed=False,
        athlete_group="Ada Example",
        event_group="Championship 2026",
    )
    assert record.analysis_allowed and not record.training_allowed
    assert "Ada" not in record.pseudonymous_athlete_key
    assert len(record.pseudonymous_athlete_key) == 64
    record.training_allowed = True
    with pytest.raises(ValueError, match="append-only"):
        record.save()
    assert organization.audit_events.get(action="dataset.source-registered").metadata["permissions"]["training"] is False


@pytest.mark.django_db
def test_evidence_share_is_recipient_scoped_expiring_and_revocable():
    admin, organization, _ = context()
    recipient = User.objects.create_user("recipient", email="recipient@example.test")
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(organization=organization, display_name="Ada", license_number="A-1", level=level)
    media = MediaAsset.objects.create(organization=organization, gymnast=gymnast, kind=MediaAsset.Kind.TRAINING, recorded_at=timezone.now(), state=MediaAsset.State.STORED, object_key="org/video.mp4", sha256="b" * 64)
    grant, token = create_evidence_share(media=media, actor=admin, recipient=recipient.email, actions=["view"], ttl_minutes=30)
    assert validate_evidence_share(raw_token=token, user=recipient, action="view") == grant
    with pytest.raises(PermissionError):
        validate_evidence_share(raw_token=token, user=recipient, action="download")
    revoke_evidence_share(grant=grant, actor=admin, reason="Shared in error")
    with pytest.raises(PermissionError):
        validate_evidence_share(raw_token=token, user=recipient, action="view")


@pytest.mark.django_db
def test_workspace_selector_changes_active_organization(client):
    user, _first, _ = context("first")
    second = Organization.objects.create(name="Second", slug="second")
    Membership.objects.create(user=user, organization=second, role=Membership.Role.VIEWER)
    client.force_login(user)
    response = client.post(reverse("organization-select"), {"organization_id": second.id})
    assert response.status_code == 302
    assert client.session["wagvid_organization_id"] == str(second.id)
    assert client.get(reverse("dashboard")).context["organization"] == second

    blocked = client.post(
        reverse("organization-select"),
        {"organization_id": second.id, "next": "https://attacker.example/steal"},
    )
    assert blocked.url == reverse("dashboard")


@pytest.mark.django_db
def test_governance_ui_and_audit_export_are_admin_scoped(client):
    admin, organization, _ = context("admin-ui")
    organization.audit_events.create(actor=admin, action="test.event", object_type="test", object_id="1")
    client.force_login(admin)
    assert client.get(reverse("governance-admin")).status_code == 200
    export = client.get(reverse("audit-export"))
    assert export.status_code == 200
    assert "test.event" in export.content.decode("utf-8-sig")

    organization.audit_events.create(
        actor=admin, action="test.formula", object_type="test", object_id="2", reason="=CMD()"
    )
    safe_export = client.get(reverse("audit-export")).content.decode("utf-8-sig")
    assert "'=CMD()" in safe_export

    viewer, viewer_org, _ = context("viewer-ui", Membership.Role.VIEWER)
    client.force_login(viewer)
    assert client.get(reverse("governance-admin")).status_code == 403
    assert viewer_org.audit_events.count() == 0


@pytest.mark.django_db
def test_dataset_export_does_not_include_raw_group_identifiers(client):
    admin, organization, _ = context("dataset-export")
    register_dataset_source(
        organization=organization, actor=admin, source_reference="internal://one", immutable_digest="c" * 64,
        rights_reference="rights-1", athlete_group="Full Athlete Name", event_group="Private Event", analysis_allowed=True,
    )
    client.force_login(admin)
    body = client.get(reverse("dataset-governance-export")).content.decode()
    assert "Full Athlete Name" not in body
    assert "Private Event" not in body
    assert "rights-1" in body
