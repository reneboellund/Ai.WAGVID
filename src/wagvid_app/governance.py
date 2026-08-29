"""Governed identity, configuration, dataset and evidence-sharing operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import (
    ConfigurationRevision,
    DatasetGovernanceRecord,
    EvidenceShareGrant,
    Membership,
    OrganizationInvitation,
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _require_admin(actor, organization):
    if not actor.wagvid_memberships.filter(organization=organization, active=True, role__in=[Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN]).exists():
        raise PermissionError("administrator role is required")


def _audit(organization, actor, action, object_type, object_id, *, reason="", metadata=None):
    return organization.audit_events.create(actor=actor, action=action, object_type=object_type, object_id=str(object_id), reason=reason, metadata=metadata or {})


@transaction.atomic
def invite_member(*, organization, actor, email: str, role: str, ttl_hours: int = 72):
    _require_admin(actor, organization)
    if role not in Membership.Role.values or role == Membership.Role.SYSTEM_ADMIN:
        raise ValueError("invalid invitation role")
    normalized_email = email.strip().lower()
    try:
        validate_email(normalized_email)
    except ValidationError as error:
        raise ValueError("valid invitation email is required") from error
    raw_token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation.objects.create(
        organization=organization,
        email=normalized_email,
        role=role,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        invited_by=actor,
        expires_at=timezone.now() + timedelta(hours=max(1, min(ttl_hours, 168))),
    )
    _audit(organization, actor, "membership.invited", "organization-invitation", invitation.id, metadata={"email": invitation.email, "role": role})
    return invitation, raw_token


@transaction.atomic
def accept_invitation(*, raw_token: str, user):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    invitation = OrganizationInvitation.objects.select_for_update().get(token_hash=token_hash)
    if invitation.state != OrganizationInvitation.State.PENDING or invitation.expires_at <= timezone.now():
        raise ValueError("invitation is not active")
    if user.email.lower() != invitation.email:
        raise PermissionError("invitation recipient does not match")
    Membership.objects.update_or_create(organization=invitation.organization, user=user, defaults={"role": invitation.role, "active": True})
    invitation.state = OrganizationInvitation.State.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["state", "accepted_by", "accepted_at", "updated_at"])
    _audit(invitation.organization, user, "membership.invitation-accepted", "organization-invitation", invitation.id)
    return invitation


@transaction.atomic
def change_member_role(*, membership, actor, role: str, active: bool, reason: str):
    _require_admin(actor, membership.organization)
    if role not in Membership.Role.values or not reason.strip():
        raise ValueError("valid role and reason are required")
    if membership.user_id == actor.id and (not active or role not in [Membership.Role.SYSTEM_ADMIN, Membership.Role.ORGANIZATION_ADMIN]):
        raise ValueError("administrators cannot remove their own administrative access")
    previous = {"role": membership.role, "active": membership.active}
    membership.role, membership.active = role, active
    membership.save(update_fields=["role", "active", "updated_at"])
    _audit(membership.organization, actor, "membership.changed", "membership", membership.id, reason=reason.strip(), metadata={"previous": previous, "current": {"role": role, "active": active}})
    return membership


def _reject_plaintext_secrets(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else key
            if any(marker in key.lower() for marker in ("secret", "password", "token", "api_key")) and item and not (isinstance(item, str) and item.startswith(("env:", "vault:", "secret:"))):
                raise ValueError(f"{current} must be a secret reference")
            _reject_plaintext_secrets(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_plaintext_secrets(item, f"{path}[{index}]")


@transaction.atomic
def create_configuration_revision(*, organization, actor, namespace: str, values: dict, reason: str, freeze: bool = False):
    _require_admin(actor, organization)
    if not namespace.strip() or not reason.strip():
        raise ValueError("namespace and reason are required")
    if not isinstance(values, dict):
        raise TypeError("configuration values must be a JSON object")
    _reject_plaintext_secrets(values)
    previous = organization.configuration_revisions.select_for_update().filter(namespace=namespace).order_by("-revision").first()
    revision = ConfigurationRevision.objects.create(
        organization=organization,
        namespace=namespace.strip(),
        revision=(previous.revision + 1 if previous else 1),
        values=values,
        digest=_digest(values),
        reason=reason.strip(),
        created_by=actor,
        state="frozen" if freeze else "draft",
        frozen_at=timezone.now() if freeze else None,
    )
    _audit(organization, actor, "configuration.revision-created", "configuration-revision", revision.id, reason=reason, metadata={"namespace": namespace, "revision": revision.revision, "digest": revision.digest, "state": revision.state})
    return revision


def pseudonymous_key(*, organization_id, category: str, external_id: str) -> str:
    material = f"{organization_id}:{category}:{external_id}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), material, hashlib.sha256).hexdigest()


@transaction.atomic
def register_dataset_source(*, organization, actor, source_reference: str, immutable_digest: str, rights_reference: str, consent_reference: str = "", analysis_allowed=False, retention_allowed=False, training_allowed=False, export_allowed=False, athlete_group: str, event_group: str, split_manifest_digest: str = "", label_provenance=None):
    _require_admin(actor, organization)
    digest_valid = len(immutable_digest) == 64 and all(character in "0123456789abcdefABCDEF" for character in immutable_digest)
    split_valid = not split_manifest_digest or (len(split_manifest_digest) == 64 and all(character in "0123456789abcdefABCDEF" for character in split_manifest_digest))
    if not digest_valid or not split_valid or not source_reference.strip() or not rights_reference.strip() or not athlete_group.strip() or not event_group.strip():
        raise ValueError("immutable SHA-256 and rights reference are required")
    record = DatasetGovernanceRecord.objects.create(
        organization=organization, source_reference=source_reference, immutable_digest=immutable_digest.lower(), rights_reference=rights_reference,
        consent_reference=consent_reference, analysis_allowed=analysis_allowed, retention_allowed=retention_allowed, training_allowed=training_allowed,
        export_allowed=export_allowed, pseudonymous_athlete_key=pseudonymous_key(organization_id=organization.id, category="athlete", external_id=athlete_group),
        pseudonymous_event_key=pseudonymous_key(organization_id=organization.id, category="event", external_id=event_group), split_manifest_digest=split_manifest_digest,
        label_provenance=label_provenance or {}, approved_by=actor,
    )
    _audit(organization, actor, "dataset.source-registered", "dataset-governance-record", record.id, metadata={"digest": immutable_digest, "permissions": {"analysis": analysis_allowed, "retention": retention_allowed, "training": training_allowed, "export": export_allowed}})
    return record


@transaction.atomic
def create_evidence_share(*, media, actor, recipient: str, actions: list[str], ttl_minutes: int = 30):
    _require_admin(actor, media.organization)
    allowed = {"view", "download"}
    if not recipient.strip() or not actions or not set(actions).issubset(allowed):
        raise ValueError("share actions must be view and/or download")
    if media.state != media.State.STORED or not media.object_key or len(media.sha256) != 64:
        raise ValueError("only integrity-complete stored media can be shared")
    raw_token = secrets.token_urlsafe(32)
    grant = EvidenceShareGrant.objects.create(
        organization=media.organization, media=media, recipient=recipient.strip(), actions=sorted(set(actions)),
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(minutes=max(1, min(ttl_minutes, 1440))), created_by=actor,
    )
    _audit(media.organization, actor, "evidence.share-created", "evidence-share-grant", grant.id, metadata={"media_id": str(media.id), "recipient": recipient, "actions": grant.actions, "expires_at": grant.expires_at.isoformat()})
    return grant, raw_token


@transaction.atomic
def revoke_evidence_share(*, grant, actor, reason: str):
    _require_admin(actor, grant.organization)
    if not reason.strip():
        raise ValueError("revocation reason is required")
    grant.revoked_at, grant.revoked_by, grant.revoke_reason = timezone.now(), actor, reason.strip()
    grant.save(update_fields=["revoked_at", "revoked_by", "revoke_reason", "updated_at"])
    _audit(grant.organization, actor, "evidence.share-revoked", "evidence-share-grant", grant.id, reason=reason)
    return grant


def validate_evidence_share(*, raw_token: str, user, action: str) -> EvidenceShareGrant:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    grant = EvidenceShareGrant.objects.select_related("media", "organization").get(token_hash=token_hash)
    identities = {user.get_username().lower(), user.email.lower()}
    if grant.recipient.lower() not in identities:
        raise PermissionError("share recipient does not match")
    if grant.revoked_at or grant.expires_at <= timezone.now() or action not in grant.actions:
        raise PermissionError("share is expired, revoked or does not allow this action")
    _audit(grant.organization, user, "evidence.share-used", "evidence-share-grant", grant.id, metadata={"action": action, "media_id": str(grant.media_id)})
    return grant
