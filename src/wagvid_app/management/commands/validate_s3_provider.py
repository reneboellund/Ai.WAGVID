"""Opt-in safe S3 contract validation against a dedicated lab bucket/prefix."""

from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError

from wagvid_app.object_provider import ProviderType, StorageConnectionProfile
from wagvid_app.s3_provider import create_boto3_s3_client
from wagvid_app.s3_validation import run_safe_contract_probe


class Command(BaseCommand):
    help = "Run an explicit safe S3 provider contract probe; never runs automatically"

    def add_arguments(self, parser):
        parser.add_argument("--provider-id", required=True)
        parser.add_argument("--provider-type", required=True, choices=[item.value for item in ProviderType if item != ProviderType.LOCAL])
        parser.add_argument("--endpoint", required=True)
        parser.add_argument("--region")
        parser.add_argument("--bucket", required=True)
        parser.add_argument("--prefix", default="ai-wagvid-capability-probe")
        parser.add_argument("--access-key-env", default="WAGVID_S3_ACCESS_KEY_ID")
        parser.add_argument("--secret-key-env", default="WAGVID_S3_SECRET_ACCESS_KEY")
        parser.add_argument("--session-token-env", default="WAGVID_S3_SESSION_TOKEN")
        parser.add_argument("--ca-bundle-path")
        parser.add_argument("--addressing-style", choices=["auto", "virtual", "path"], default="auto")
        parser.add_argument("--test-presign", action="store_true")
        parser.add_argument("--no-delete", action="store_true")
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        if options["confirm"] != "RUN SAFE S3 PROBE":
            raise CommandError("Explicit confirmation must be exactly: RUN SAFE S3 PROBE")
        endpoint = options["endpoint"]
        if not endpoint.lower().startswith("https://"):
            raise CommandError("S3 validation endpoint must use HTTPS")

        access_key = os.environ.get(options["access_key_env"])
        secret_key = os.environ.get(options["secret_key_env"])
        session_token = os.environ.get(options["session_token_env"])
        if bool(access_key) != bool(secret_key):
            raise CommandError("Access key and secret key environment variables must be supplied together")

        profile = StorageConnectionProfile(
            provider_id=options["provider_id"],
            provider_type=ProviderType(options["provider_type"]),
            endpoint=endpoint,
            region=options["region"],
            credential_ref=(
                f"env://{options['access_key_env']}+{options['secret_key_env']}"
                if access_key
                else "workload-identity://default"
            ),
            ca_bundle_ref="resolved-at-runtime" if options["ca_bundle_path"] else None,
            addressing_style=options["addressing_style"],
            tls_required=True,
        )
        client = create_boto3_s3_client(
            profile,
            access_key_id=access_key,
            secret_access_key=secret_key,
            session_token=session_token,
            ca_bundle_path=options["ca_bundle_path"],
        )
        result = run_safe_contract_probe(
            client,
            provider_id=profile.provider_id,
            bucket=options["bucket"],
            prefix=options["prefix"],
            allow_delete=not options["no_delete"],
            test_presign=options["test_presign"],
        )
        payload = {
            "provider_id": result.provider_id,
            "provider_type": profile.provider_type.value,
            "bucket": result.bucket,
            "state": result.state.value,
            "tested_at": result.tested_at.isoformat() if result.tested_at else None,
            "core_validated": result.core_validated,
            "passed_operations": sorted(result.passed_operations),
            "failed_operations": list(result.failed_operations),
            "verified_features": sorted(item.value for item in result.verified_features),
            "notes": list(result.notes),
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
        if not result.core_validated:
            raise CommandError("Provider failed the required Ai.WAGVID S3 contract")
