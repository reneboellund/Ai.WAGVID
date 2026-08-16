from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from wagvid_app.models import Level, Membership, Organization


class Command(BaseCommand):
    help = "Create or update a development organization, owner and starter levels."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--organization", default="Ai.WAGVID Development")
        parser.add_argument("--slug", default="development")

    @transaction.atomic
    def handle(self, *args, **options):
        organization, _ = Organization.objects.get_or_create(
            slug=options["slug"], defaults={"name": options["organization"]}
        )
        user, created = get_user_model().objects.get_or_create(
            username=options["username"], defaults={"is_staff": True}
        )
        Membership.objects.update_or_create(
            organization=organization,
            user=user,
            defaults={"role": Membership.Role.SYSTEM_ADMIN, "active": True},
        )
        for level_name in ("Basis", "Trin 1", "Trin 2", "Trin 3"):
            Level.objects.get_or_create(organization=organization, name=level_name)
        organization.audit_events.create(
            actor=user,
            action="system.bootstrap",
            object_type="organization",
            object_id=str(organization.id),
            metadata={"user_created": created},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Ready: {organization.name}. Set a password with changepassword {user.username}."
            )
        )
