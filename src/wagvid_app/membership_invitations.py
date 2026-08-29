"""Persistent organization membership invitations.

The invitation token itself is never stored. Only its SHA-256 digest is persisted so a
database read does not reveal usable invitation links.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .models import Membership, Organization


class MembershipInvitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="membership_invitations",
    )
    email = models.EmailField(max_length=254, db_index=True)
    role = models.CharField(max_length=32, choices=Membership.Role.choices)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wagvid_membership_invitations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wagvid_membership_invitations_accepted",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "wagvid_app"
        db_table = "wagvid_app_membershipinvitation"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "email"], name="invite_org_email_idx"),
            models.Index(fields=["organization", "expires_at"], name="invite_org_exp_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.email} -> {self.organization} ({self.role})"
