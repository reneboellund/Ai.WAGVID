from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wagvid_app.models import StorageConnection
from wagvid_app.s3_clients import create_profile_client
from wagvid_app.storage_contract import run_storage_contract_probe


class Command(BaseCommand):
    help = "Run an explicit temporary-object contract probe against one configured provider"

    def add_arguments(self, parser):
        parser.add_argument("connection_id")
        parser.add_argument("--bucket", required=True)
        parser.add_argument("--prefix", default="wagvid-contract-tests")
        parser.add_argument("--approve-test-objects", action="store_true")

    def handle(self, *args, **options):
        if not options["approve_test_objects"]:
            raise CommandError("--approve-test-objects is required; the probe creates temporary objects")
        try:
            connection = StorageConnection.objects.select_related("organization").get(
                pk=options["connection_id"], active=True
            )
        except (StorageConnection.DoesNotExist, ValueError) as error:
            raise CommandError("active storage connection was not found") from error
        report = run_storage_contract_probe(
            create_profile_client(connection),
            provider_id=connection.provider,
            governance_profile=connection.governance_profile,
            bucket=options["bucket"],
            test_prefix=options["prefix"],
            allow_mutation=True,
        )
        with transaction.atomic():
            locked = StorageConnection.objects.select_for_update().get(pk=connection.id)
            locked.capability_snapshot = {
                "verified": report.verified,
                "checks": list(report.checks),
                "issues": list(report.issues),
                "bucket": report.bucket,
            }
            locked.support_state = report.support_state
            locked.status = (
                StorageConnection.Status.VERIFIED
                if report.support_state == "validated"
                else StorageConnection.Status.DEGRADED
            )
            locked.save(
                update_fields=["capability_snapshot", "support_state", "status", "updated_at"]
            )
            locked.organization.audit_events.create(
                action="storage.provider-contract-validated",
                object_type="storage-connection",
                object_id=str(locked.id),
                metadata={
                    "provider": locked.provider,
                    "support_state": report.support_state,
                    "checks": list(report.checks),
                    "issue_count": len(report.issues),
                },
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"provider={connection.provider} support={report.support_state} "
                f"checks={len(report.checks)} issues={len(report.issues)}"
            )
        )
