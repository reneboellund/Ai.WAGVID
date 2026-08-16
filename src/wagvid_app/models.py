import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MinValueValidator
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(TimestampedModel):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = "system-admin", "Systemadministrator"
        ORGANIZATION_ADMIN = "organization-admin", "Organisationsadministrator"
        OPERATOR = "operator", "Operatør"
        COACH = "coach", "Træner"
        REVIEWER = "reviewer", "Reviewer"
        RESEARCHER = "researcher", "Forsker"
        VIEWER = "viewer", "Læser"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wagvid_memberships"
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="one_membership_per_org")
        ]


class Level(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="levels")
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_level_per_org")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Gymnast(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="gymnasts"
    )
    display_name = models.CharField(max_length=200)
    license_number = models.CharField(max_length=100)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="gymnasts")
    kiga_id = models.CharField(max_length=120, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "license_number"], name="unique_license_per_org"
            )
        ]
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.license_number})"


class Device(TimestampedModel):
    class State(models.TextChoices):
        UNPAIRED = "unpaired", "Ikke parret"
        OFFLINE = "offline", "Offline"
        READY = "ready", "Klar"
        ARMED = "armed", "Auto klar"
        RECORDING = "recording", "Optager"
        FINALIZING = "finalizing", "Gemmer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=120)
    device_key = models.CharField(max_length=160, unique=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.UNPAIRED)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    free_storage_bytes = models.BigIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0)]
    )
    queued_uploads = models.PositiveIntegerField(default=0)
    api_token_hash = models.CharField(max_length=256, blank=True)

    def set_api_token(self, raw_token: str) -> None:
        self.api_token_hash = make_password(raw_token)

    def check_api_token(self, raw_token: str) -> bool:
        return bool(self.api_token_hash) and check_password(raw_token, self.api_token_hash)


class MediaAsset(TimestampedModel):
    class Kind(models.TextChoices):
        ROUTINE = "routine", "Hel øvelse"
        TRAINING = "training", "Træning"
        DRILL = "drill", "Moment"
        COMPETITION = "competition", "Konkurrence"

    class State(models.TextChoices):
        QUEUED = "queued", "Venter"
        UPLOADING = "uploading", "Uploader"
        STORED = "stored", "Gemt"
        QUARANTINED = "quarantined", "Karantæne"
        UNUSABLE = "unusable", "Ubrugelig"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="media")
    gymnast = models.ForeignKey(Gymnast, on_delete=models.PROTECT, related_name="media")
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="media"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED)
    object_key = models.CharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    original_retained = models.BooleanField(default=True)
    recorded_at = models.DateTimeField()


class AnalysisJob(TimestampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Kladde"
        QUEUED = "queued", "Venter"
        BLOCKED = "blocked", "Blokeret"
        RUNNING = "running", "Kører"
        NEEDS_REVIEW = "needs-review", "Kræver review"
        FAILED_RETRYABLE = "failed-retryable", "Kan prøves igen"
        FAILED_TERMINAL = "failed-terminal", "Stoppet"
        COMPLETED = "completed", "Færdig"
        CANCELLED = "cancelled", "Annulleret"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="analysis_jobs"
    )
    media = models.ForeignKey(MediaAsset, on_delete=models.PROTECT, related_name="analysis_jobs")
    state = models.CharField(max_length=24, choices=State.choices, default=State.DRAFT)
    scope = models.CharField(max_length=32)
    rulepack_id = models.CharField(max_length=200)
    model_profile = models.CharField(max_length=120)
    progress_percent = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0)]
    )
    revision = models.PositiveIntegerField(default=1)
    error_code = models.CharField(max_length=100, blank=True)
    leased_by = models.ForeignKey(
        "WorkerNode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leased_jobs",
    )
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["media", "revision"], name="unique_analysis_revision")
        ]


class ExchangeJob(TimestampedModel):
    class Direction(models.TextChoices):
        IMPORT = "import", "Import"
        EXPORT = "export", "Eksport"

    class State(models.TextChoices):
        DRAFT = "draft", "Kladde"
        VALIDATING = "validating", "Validerer"
        READY = "ready", "Klar"
        RUNNING = "running", "Kører"
        FAILED = "failed", "Fejlet"
        COMPLETED = "completed", "Færdig"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="exchange_jobs"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    kind = models.CharField(max_length=80)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)
    schema_version = models.CharField(max_length=40)
    result_summary = models.JSONField(default=dict)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120)
    object_id = models.CharField(max_length=200)
    reason = models.TextField(blank=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    metadata = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValueError("Audit events are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit events are append-only")


class UploadSession(TimestampedModel):
    class State(models.TextChoices):
        OPEN = "open", "Åben"
        UPLOADING = "uploading", "Uploader"
        VERIFYING = "verifying", "Verificerer"
        COMPLETED = "completed", "Færdig"
        FAILED = "failed", "Fejlet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="upload_sessions"
    )
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="upload_sessions"
    )
    capture_id = models.UUIDField()
    # Legacy/incomplete sessions may predate capture metadata. The device API
    # requires these fields for every new upload, while nullable storage keeps
    # upgrades safe and lets operators inspect or retire abandoned sessions.
    gymnast = models.ForeignKey(
        Gymnast,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="upload_sessions",
    )
    kind = models.CharField(max_length=20, choices=MediaAsset.Kind.choices, blank=True)
    recorded_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=160)
    local_filename = models.CharField(max_length=255)
    expected_bytes = models.BigIntegerField(validators=[MinValueValidator(1)])
    received_bytes = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    expected_sha256 = models.CharField(max_length=64)
    object_key = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.OPEN)
    last_error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_upload_idempotency_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(received_bytes__lte=models.F("expected_bytes")),
                name="upload_received_not_above_expected",
            ),
        ]


class WorkerNode(TimestampedModel):
    class State(models.TextChoices):
        ONLINE = "online", "Online"
        DRAINING = "draining", "Dræner"
        OFFLINE = "offline", "Offline"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.OFFLINE)
    capabilities = models.JSONField(default=list)
    active_jobs = models.PositiveIntegerField(default=0)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)


class SystemAlert(TimestampedModel):
    class Severity(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Advarsel"
        CRITICAL = "critical", "Kritisk"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="system_alerts",
    )
    code = models.CharField(max_length=120)
    severity = models.CharField(max_length=12, choices=Severity.choices)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=200, blank=True)
    message = models.CharField(max_length=500)
    active = models.BooleanField(default=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["active", "severity"])]
