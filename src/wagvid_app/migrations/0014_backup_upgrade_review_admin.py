import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wagvid_app", "0013_storage_provider_framework"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="analysisjob", name="review_priority", field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name="analysisjob", name="review_reason", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="analysisjob", name="review_assignee", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_wagvid_reviews", to=settings.AUTH_USER_MODEL)),
        migrations.CreateModel(
            name="SystemBackup",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("state", models.CharField(choices=[("created", "Oprettet"), ("verifying", "Verificerer"), ("verified", "Verificeret"), ("failed", "Fejlet"), ("expired", "Udløbet")], default="created", max_length=16)),
                ("purpose", models.CharField(choices=[("manual", "Manuel"), ("scheduled", "Planlagt"), ("pre-upgrade", "Før opgradering"), ("pre-migration", "Før migrering"), ("pre-destructive", "Før destruktiv handling")], max_length=24)),
                ("destination", models.CharField(max_length=300)), ("retention_class", models.CharField(default="daily", max_length=40)),
                ("application_release", models.CharField(max_length=80)), ("git_sha", models.CharField(max_length=64)),
                ("migration_heads", models.JSONField(default=list)), ("manifest", models.JSONField(default=dict)),
                ("manifest_sha256", models.CharField(blank=True, max_length=64)), ("verification", models.JSONField(default=dict)),
                ("verified_at", models.DateTimeField(blank=True, null=True)), ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="MaintenanceState",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("active", models.BooleanField(default=False)), ("read_only", models.BooleanField(default=True)),
                ("reason", models.CharField(blank=True, max_length=300)), ("entered_at", models.DateTimeField(blank=True, null=True)),
                ("entered_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="UpgradeJournal",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_release", models.CharField(max_length=80)), ("target_release", models.CharField(max_length=80)),
                ("target_manifest", models.JSONField(default=dict)),
                ("state", models.CharField(choices=[("planned", "Planlagt"), ("blocked", "Blokeret"), ("approved", "Godkendt"), ("running", "Kører"), ("verifying", "Verificerer"), ("completed", "Færdig"), ("failed", "Fejlet"), ("rollback-staged", "Rollback klargjort")], default="planned", max_length=24)),
                ("preflight", models.JSONField(default=dict)), ("migrations_planned", models.JSONField(default=list)),
                ("config_migrations", models.JSONField(default=list)), ("verification", models.JSONField(default=dict)),
                ("started_at", models.DateTimeField(blank=True, null=True)), ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("failure_code", models.CharField(blank=True, max_length=100)),
                ("backup", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="upgrades", to="wagvid_app.systembackup")),
                ("initiated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
