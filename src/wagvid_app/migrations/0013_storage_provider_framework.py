import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wagvid_app", "0012_storageconnection_storagebucket_storedobjectrecord")]

    operations = [
        migrations.CreateModel(
            name="StorageRoleAssignment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.CharField(max_length=20)),
                ("active", models.BooleanField(default=True)),
                (
                    "connection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="role_assignments",
                        to="wagvid_app.storageconnection",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="storage_role_assignments",
                        to="wagvid_app.organization",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="StorageTransfer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("target_key", models.CharField(max_length=700)),
                ("target_version_id", models.CharField(blank=True, max_length=240)),
                ("expected_sha256", models.CharField(max_length=64)),
                ("expected_size_bytes", models.BigIntegerField(validators=[django.core.validators.MinValueValidator(0)])),
                ("bytes_copied", models.BigIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)])),
                ("state", models.CharField(choices=[("planned", "Planlagt"), ("copying", "Kopierer"), ("verifying", "Verificerer"), ("completed", "Færdig"), ("failed", "Fejlet"), ("cancelled", "Annulleret")], default="planned", max_length=16)),
                ("client_request_id", models.CharField(max_length=160)),
                ("delete_source_approved", models.BooleanField(default=False)),
                ("error_code", models.CharField(blank=True, max_length=80)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="storage_transfers", to="wagvid_app.organization")),
                ("source_object", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_transfers", to="wagvid_app.storedobjectrecord")),
                ("target_bucket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_transfers", to="wagvid_app.storagebucket")),
                ("target_connection", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="incoming_transfers", to="wagvid_app.storageconnection")),
            ],
        ),
        migrations.AlterField(
            model_name="storageconnection",
            name="pricing_model",
            field=models.CharField(
                choices=[
                    ("none", "Ingen minimumsperiode"),
                    ("pay-go", "Pay-Go (90 dage)"),
                    ("rcs", "Reserved Capacity (30 dage)"),
                    ("custom", "Aftalespecifik"),
                ],
                default="pay-go",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="storageconnection",
            name="provider",
            field=models.CharField(
                choices=[
                    ("wasabi", "Wasabi"),
                    ("aws-s3", "Amazon S3"),
                    ("ontap-s3", "NetApp ONTAP S3"),
                    ("vast-s3", "VAST Data S3"),
                    ("ootbi-s3", "Object First Ootbi"),
                ],
                default="wasabi",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="auth_mode",
            field=models.CharField(
                choices=[
                    ("access-key", "Access key"),
                    ("workload-identity", "Workload identity"),
                ],
                default="access-key",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="role_arn",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AlterField(
            model_name="storageconnection",
            name="access_key_secret_ref",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="storageconnection",
            name="secret_key_secret_ref",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="addressing_style",
            field=models.CharField(
                choices=[("virtual", "Virtual host"), ("path", "Path style")],
                default="virtual",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="capability_snapshot",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="custom_ca_secret_ref",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="existing_bucket_map",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="governance_profile",
            field=models.CharField(
                choices=[
                    ("standard", "Standard"),
                    ("evidence-immutable", "Immutable evidence"),
                    ("backup-target", "Backup target"),
                ],
                default="standard",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="provisioning_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="support_state",
            field=models.CharField(
                choices=[
                    ("unvalidated", "Ikke valideret"),
                    ("validated", "Valideret"),
                    ("limited", "Begrænset"),
                    ("incompatible", "Inkompatibel"),
                ],
                default="unvalidated",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="storageconnection",
            name="tls_verify",
            field=models.BooleanField(default=True),
        ),
        migrations.AddConstraint(
            model_name="storageroleassignment",
            constraint=models.UniqueConstraint(
                fields=("organization", "role"), name="unique_storage_provider_per_role"
            ),
        ),
        migrations.AddConstraint(
            model_name="storagetransfer",
            constraint=models.UniqueConstraint(fields=("organization", "client_request_id"), name="unique_storage_transfer_request_per_org"),
        ),
        migrations.AddConstraint(
            model_name="storagetransfer",
            constraint=models.CheckConstraint(condition=models.Q(("bytes_copied__lte", models.F("expected_size_bytes"))), name="storage_transfer_progress_not_above_size"),
        ),
    ]
