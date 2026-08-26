import uuid

import django.db.models.deletion
from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("wagvid_app", "0011_mediaasset_source_metadata")]

    operations = [
        migrations.CreateModel(
            name="StorageConnection",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("provider", models.CharField(default="wasabi", max_length=20)),
                ("status", models.CharField(choices=[("disconnected", "Ikke forbundet"), ("configured", "Konfigureret"), ("verified", "Verificeret"), ("degraded", "Kræver opmærksomhed")], default="disconnected", max_length=20)),
                ("project_slug", models.SlugField(default="wagvid", max_length=24)),
                ("environment", models.SlugField(default="production", max_length=16)),
                ("region", models.CharField(default="eu-central-1", max_length=40)),
                ("endpoint", models.URLField(max_length=300)),
                ("account_fingerprint", models.CharField(max_length=16)),
                ("access_key_secret_ref", models.CharField(max_length=200)),
                ("secret_key_secret_ref", models.CharField(max_length=200)),
                ("originals_shards", models.PositiveSmallIntegerField(default=2)),
                ("derivatives_shards", models.PositiveSmallIntegerField(default=2)),
                ("include_audit_bucket", models.BooleanField(default=True)),
                ("enable_versioning", models.BooleanField(default=True)),
                ("pricing_model", models.CharField(choices=[("pay-go", "Pay-Go (90 dage)"), ("rcs", "Reserved Capacity (30 dage)"), ("custom", "Aftalespecifik")], default="pay-go", max_length=20)),
                ("minimum_storage_days", models.PositiveSmallIntegerField(default=90)),
                ("routing_revision", models.PositiveIntegerField(default=1)),
                ("desired_plan_digest", models.CharField(blank=True, max_length=64)),
                ("last_preflight", models.JSONField(default=dict)),
                ("last_preflight_at", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="storage_connections", to="wagvid_app.organization")),
            ],
        ),
        migrations.CreateModel(
            name="StorageBucket",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("role", models.CharField(max_length=20)),
                ("shard", models.PositiveSmallIntegerField(default=0)),
                ("bucket_name", models.CharField(max_length=63)),
                ("region", models.CharField(max_length=40)),
                ("state", models.CharField(choices=[("desired", "Planlagt"), ("discovered", "Fundet"), ("ready", "Klar"), ("conflict", "Konflikt"), ("retired", "Udfaset")], default="desired", max_length=20)),
                ("routing_revision", models.PositiveIntegerField()),
                ("private", models.BooleanField(default=True)),
                ("versioning", models.BooleanField(default=False)),
                ("object_lock", models.BooleanField(default=False)),
                ("provider_metadata", models.JSONField(default=dict)),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="buckets", to="wagvid_app.storageconnection")),
            ],
        ),
        migrations.CreateModel(
            name="StoredObjectRecord",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("object_key", models.CharField(max_length=700)),
                ("version_id", models.CharField(blank=True, max_length=240)),
                ("role", models.CharField(max_length=20)),
                ("content_sha256", models.CharField(max_length=64)),
                ("size_bytes", models.BigIntegerField(validators=[MinValueValidator(0)])),
                ("uploaded_at", models.DateTimeField()),
                ("billable_until", models.DateTimeField()),
                ("retention_until", models.DateTimeField(blank=True, null=True)),
                ("legal_hold", models.BooleanField(default=False)),
                ("state", models.CharField(choices=[("active", "Aktiv"), ("quarantined", "Soft-delete karantæne"), ("pending-delete", "Afventer fysisk sletning"), ("deleted", "Fysisk slettet")], default="active", max_length=20)),
                ("delete_requested_at", models.DateTimeField(blank=True, null=True)),
                ("physical_delete_after", models.DateTimeField(blank=True, null=True)),
                ("deletion_reason", models.TextField(blank=True)),
                ("bucket", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stored_object_records", to="wagvid_app.storagebucket")),
                ("connection", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stored_object_records", to="wagvid_app.storageconnection")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stored_objects", to="wagvid_app.organization")),
            ],
        ),
        migrations.AddConstraint(model_name="storageconnection", constraint=models.UniqueConstraint(fields=("organization", "name"), name="unique_storage_connection_name_per_org")),
        migrations.AddConstraint(model_name="storageconnection", constraint=models.CheckConstraint(condition=models.Q(("originals_shards__gte", 1), ("originals_shards__lte", 32)), name="storage_original_shards_1_32")),
        migrations.AddConstraint(model_name="storageconnection", constraint=models.CheckConstraint(condition=models.Q(("derivatives_shards__gte", 1), ("derivatives_shards__lte", 32)), name="storage_derivative_shards_1_32")),
        migrations.AddConstraint(model_name="storagebucket", constraint=models.UniqueConstraint(fields=("connection", "role", "shard", "routing_revision"), name="unique_storage_bucket_route")),
        migrations.AddConstraint(model_name="storagebucket", constraint=models.UniqueConstraint(fields=("connection", "bucket_name"), name="unique_bucket_name_per_connection")),
        migrations.AddConstraint(model_name="storedobjectrecord", constraint=models.UniqueConstraint(fields=("connection", "bucket", "object_key", "version_id"), name="unique_stored_object_version")),
        migrations.AddConstraint(model_name="storedobjectrecord", constraint=models.CheckConstraint(condition=models.Q(("billable_until__gte", models.F("uploaded_at"))), name="stored_object_billable_after_upload")),
        migrations.AddIndex(model_name="storedobjectrecord", index=models.Index(fields=["organization", "state"], name="wagvid_app__organiz_663a0c_idx")),
        migrations.AddIndex(model_name="storedobjectrecord", index=models.Index(fields=["billable_until", "state"], name="wagvid_app__billabl_bba1bb_idx")),
    ]
