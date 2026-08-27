import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator
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
    class Discipline(models.TextChoices):
        WAG = "WAG", "Kvindeidrætsgymnastik"
        MAG = "MAG", "Mandlig idrætsgymnastik"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="gymnasts"
    )
    display_name = models.CharField(max_length=200)
    license_number = models.CharField(max_length=100)
    discipline = models.CharField(max_length=3, choices=Discipline.choices, default=Discipline.WAG)
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


class Event(TimestampedModel):
    class Kind(models.TextChoices):
        COMPETITION = "competition", "Konkurrence"
        TRAINING = "training", "Træning"
        TEST = "test", "Test"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=240)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    venue = models.CharField(max_length=240, blank=True)
    timezone_name = models.CharField(max_length=80, default="Europe/Copenhagen")
    city = models.CharField(max_length=160, blank=True)
    country_code = models.CharField(max_length=2, blank=True)
    organizer = models.CharField(max_length=200, blank=True)
    federation = models.CharField(max_length=200, blank=True)
    competition_level = models.CharField(max_length=120, blank=True)
    rule_profile = models.CharField(max_length=200, blank=True)
    external_source = models.CharField(max_length=80, blank=True)
    external_id = models.CharField(max_length=160, blank=True)

    class Meta:
        ordering = ["-starts_at"]


class Routine(TimestampedModel):
    class Apparatus(models.TextChoices):
        VAULT = "VT", "Spring"
        BARS = "UB", "Forskudt barre"
        BEAM = "BB", "Bom"
        FLOOR = "FX", "Gulv"
        POMMEL_HORSE = "PH", "Hest med bøjler"
        STILL_RINGS = "SR", "Ringe"
        PARALLEL_BARS = "PB", "Parallelle barrer"
        HIGH_BAR = "HB", "Reck"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="routines")
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="routines")
    gymnast = models.ForeignKey(Gymnast, on_delete=models.PROTECT, related_name="routines")
    apparatus = models.CharField(max_length=2, choices=Apparatus.choices)
    category = models.CharField(max_length=120, blank=True)
    age_category = models.CharField(max_length=120, blank=True)
    round_name = models.CharField(max_length=120, blank=True)
    rotation = models.PositiveIntegerField(null=True, blank=True)
    performed_at = models.DateTimeField(null=True, blank=True)
    start_order = models.PositiveIntegerField(null=True, blank=True)
    rulepack_id = models.CharField(max_length=200)
    external_id = models.CharField(max_length=160, blank=True)
    official_d_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    official_e_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    official_neutral = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    official_final_score = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    official_frozen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_external_routine_per_event",
            )
        ]


class ExternalMediaReference(TimestampedModel):
    class State(models.TextChoices):
        DISCOVERED = "discovered", "Fundet"
        READY = "ready", "Klar til hentning"
        IMPORTED = "imported", "Importeret"
        BLOCKED = "blocked", "Blokeret"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="external_media_references"
    )
    routine = models.ForeignKey(
        Routine, on_delete=models.CASCADE, related_name="external_media_references"
    )
    provider = models.CharField(max_length=80, default="KIGA")
    external_media_id = models.CharField(max_length=200)
    download_uri = models.URLField(max_length=1000)
    sha256 = models.CharField(max_length=64, db_index=True)
    captured_at = models.DateTimeField()
    content_type = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    camera_id = models.CharField(max_length=120, blank=True)
    view = models.CharField(max_length=120, blank=True)
    download_allowed = models.BooleanField()
    analysis_allowed = models.BooleanField()
    training_allowed = models.BooleanField()
    retention_until = models.DateField(null=True, blank=True)
    consent_reference = models.CharField(max_length=240, blank=True)
    access_policy = models.CharField(max_length=240, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DISCOVERED)
    media_asset = models.ForeignKey(
        "MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="external_sources"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "external_media_id"],
                name="unique_external_media_per_provider",
            )
        ]


class OfficialResultSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    routine = models.ForeignKey(Routine, on_delete=models.PROTECT, related_name="official_versions")
    provider = models.CharField(max_length=80)
    source = models.CharField(max_length=240)
    status = models.CharField(
        max_length=20,
        choices=[
            ("provisional", "Foreløbig"),
            ("official", "Officiel"),
            ("corrected", "Korrigeret"),
            ("withdrawn", "Tilbagetrukket"),
        ],
    )
    result_version = models.CharField(max_length=120)
    d_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    e_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    artistry = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    neutral = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    final_score = models.DecimalField(max_digits=6, decimal_places=3)
    source_captured_at = models.DateTimeField()
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["routine", "provider", "result_version"],
                name="unique_official_result_version",
            )
        ]
        ordering = ["-source_captured_at"]

    def save(self, *args, **kwargs):
        if self.pk and OfficialResultSnapshot.objects.filter(pk=self.pk).exists():
            raise ValueError("Official result snapshots are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Official result snapshots are append-only")


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
    battery_percent = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    network_type = models.CharField(max_length=40, blank=True)
    app_version = models.CharField(max_length=80, blank=True)
    active_capture_id = models.UUIDField(null=True, blank=True)
    api_token_hash = models.CharField(max_length=256, blank=True)

    def set_api_token(self, raw_token: str) -> None:
        self.api_token_hash = make_password(raw_token)

    def check_api_token(self, raw_token: str) -> bool:
        return bool(self.api_token_hash) and check_password(raw_token, self.api_token_hash)


class DevicePairingSession(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="device_pairing_sessions"
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    device = models.OneToOneField(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="pairing_session"
    )


class DeviceCommand(TimestampedModel):
    class Command(models.TextChoices):
        ARM = "arm", "Armér auto"
        DISARM = "disarm", "Deaktivér auto"
        START = "start", "Start optagelse"
        STOP = "stop", "Stop optagelse"

    class State(models.TextChoices):
        PENDING = "pending", "Afventer"
        DELIVERED = "delivered", "Leveret"
        ACCEPTED = "accepted", "Accepteret"
        REJECTED = "rejected", "Afvist"
        EXPIRED = "expired", "Udløbet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="device_commands"
    )
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=16, choices=Command.choices)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    expected_device_state = models.CharField(max_length=20, choices=Device.State.choices)
    payload = models.JSONField(default=dict)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=160)
    expires_at = models.DateTimeField(db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    rejection_code = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "idempotency_key"], name="unique_device_command_request"
            )
        ]
        ordering = ["created_at"]


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
    routine = models.ForeignKey(
        Routine, on_delete=models.SET_NULL, null=True, blank=True, related_name="media"
    )
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="media"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    state = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED)
    object_key = models.CharField(max_length=500, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    original_retained = models.BooleanField(default=True)
    recorded_at = models.DateTimeField()


class StorageConnection(TimestampedModel):
    class Provider(models.TextChoices):
        WASABI = "wasabi", "Wasabi"
        AWS_S3 = "aws-s3", "Amazon S3"
        ONTAP_S3 = "ontap-s3", "NetApp ONTAP S3"
        VAST_S3 = "vast-s3", "VAST Data S3"
        OOTBI_S3 = "ootbi-s3", "Object First Ootbi"

    class Status(models.TextChoices):
        DISCONNECTED = "disconnected", "Ikke forbundet"
        CONFIGURED = "configured", "Konfigureret"
        VERIFIED = "verified", "Verificeret"
        DEGRADED = "degraded", "Kræver opmærksomhed"

    class PricingModel(models.TextChoices):
        NONE = "none", "Ingen minimumsperiode"
        PAY_GO = "pay-go", "Pay-Go (90 dage)"
        RCS = "rcs", "Reserved Capacity (30 dage)"
        CUSTOM = "custom", "Aftalespecifik"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="storage_connections"
    )
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.WASABI)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISCONNECTED)
    project_slug = models.SlugField(max_length=24, default="wagvid")
    environment = models.SlugField(max_length=16, default="production")
    region = models.CharField(max_length=40, default="eu-central-1")
    endpoint = models.URLField(max_length=300)
    auth_mode = models.CharField(
        max_length=20,
        choices=[("access-key", "Access key"), ("workload-identity", "Workload identity")],
        default="access-key",
    )
    role_arn = models.CharField(max_length=300, blank=True)
    tls_verify = models.BooleanField(default=True)
    custom_ca_secret_ref = models.CharField(max_length=200, blank=True)
    addressing_style = models.CharField(
        max_length=12, choices=[("virtual", "Virtual host"), ("path", "Path style")],
        default="virtual",
    )
    governance_profile = models.CharField(
        max_length=24,
        choices=[
            ("standard", "Standard"),
            ("evidence-immutable", "Immutable evidence"),
            ("backup-target", "Backup target"),
        ],
        default="standard",
    )
    provisioning_enabled = models.BooleanField(default=False)
    existing_bucket_map = models.JSONField(default=dict, blank=True)
    capability_snapshot = models.JSONField(default=dict)
    support_state = models.CharField(
        max_length=16,
        choices=[
            ("unvalidated", "Ikke valideret"),
            ("validated", "Valideret"),
            ("limited", "Begrænset"),
            ("incompatible", "Inkompatibel"),
        ],
        default="unvalidated",
    )
    account_fingerprint = models.CharField(max_length=16)
    access_key_secret_ref = models.CharField(max_length=200, blank=True)
    secret_key_secret_ref = models.CharField(max_length=200, blank=True)
    originals_shards = models.PositiveSmallIntegerField(default=2)
    derivatives_shards = models.PositiveSmallIntegerField(default=2)
    include_audit_bucket = models.BooleanField(default=True)
    enable_versioning = models.BooleanField(default=True)
    pricing_model = models.CharField(
        max_length=20, choices=PricingModel.choices, default=PricingModel.PAY_GO
    )
    minimum_storage_days = models.PositiveSmallIntegerField(default=90)
    routing_revision = models.PositiveIntegerField(default=1)
    desired_plan_digest = models.CharField(max_length=64, blank=True)
    last_preflight = models.JSONField(default=dict)
    last_preflight_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="unique_storage_connection_name_per_org"
            ),
            models.CheckConstraint(
                condition=models.Q(originals_shards__gte=1, originals_shards__lte=32),
                name="storage_original_shards_1_32",
            ),
            models.CheckConstraint(
                condition=models.Q(derivatives_shards__gte=1, derivatives_shards__lte=32),
                name="storage_derivative_shards_1_32",
            ),
        ]


class StorageBucket(TimestampedModel):
    class State(models.TextChoices):
        DESIRED = "desired", "Planlagt"
        DISCOVERED = "discovered", "Fundet"
        READY = "ready", "Klar"
        CONFLICT = "conflict", "Konflikt"
        RETIRED = "retired", "Udfaset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(
        StorageConnection, on_delete=models.CASCADE, related_name="buckets"
    )
    role = models.CharField(max_length=20)
    shard = models.PositiveSmallIntegerField(default=0)
    bucket_name = models.CharField(max_length=63)
    region = models.CharField(max_length=40)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DESIRED)
    routing_revision = models.PositiveIntegerField()
    private = models.BooleanField(default=True)
    versioning = models.BooleanField(default=False)
    object_lock = models.BooleanField(default=False)
    provider_metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "role", "shard", "routing_revision"],
                name="unique_storage_bucket_route",
            ),
            models.UniqueConstraint(
                fields=["connection", "bucket_name"], name="unique_bucket_name_per_connection"
            ),
        ]


class StorageRoleAssignment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="storage_role_assignments"
    )
    role = models.CharField(max_length=20)
    connection = models.ForeignKey(
        StorageConnection, on_delete=models.PROTECT, related_name="role_assignments"
    )
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "role"], name="unique_storage_provider_per_role"
            )
        ]


class StoredObjectRecord(TimestampedModel):
    class State(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        QUARANTINED = "quarantined", "Soft-delete karantæne"
        PENDING_DELETE = "pending-delete", "Afventer fysisk sletning"
        DELETED = "deleted", "Fysisk slettet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="stored_objects"
    )
    connection = models.ForeignKey(
        StorageConnection, on_delete=models.PROTECT, related_name="stored_object_records"
    )
    bucket = models.ForeignKey(
        StorageBucket, on_delete=models.PROTECT, related_name="stored_object_records"
    )
    object_key = models.CharField(max_length=700)
    version_id = models.CharField(max_length=240, blank=True)
    role = models.CharField(max_length=20)
    content_sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField(validators=[MinValueValidator(0)])
    uploaded_at = models.DateTimeField()
    billable_until = models.DateTimeField()
    retention_until = models.DateTimeField(null=True, blank=True)
    legal_hold = models.BooleanField(default=False)
    state = models.CharField(max_length=20, choices=State.choices, default=State.ACTIVE)
    delete_requested_at = models.DateTimeField(null=True, blank=True)
    physical_delete_after = models.DateTimeField(null=True, blank=True)
    deletion_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "bucket", "object_key", "version_id"],
                name="unique_stored_object_version",
            ),
            models.CheckConstraint(
                condition=models.Q(billable_until__gte=models.F("uploaded_at")),
                name="stored_object_billable_after_upload",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "state"], name="wagvid_app__organiz_663a0c_idx"
            ),
            models.Index(
                fields=["billable_until", "state"], name="wagvid_app__billabl_bba1bb_idx"
            ),
        ]


class StorageTransfer(TimestampedModel):
    class State(models.TextChoices):
        PLANNED = "planned", "Planlagt"
        COPYING = "copying", "Kopierer"
        VERIFYING = "verifying", "Verificerer"
        COMPLETED = "completed", "Færdig"
        FAILED = "failed", "Fejlet"
        CANCELLED = "cancelled", "Annulleret"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="storage_transfers"
    )
    source_object = models.ForeignKey(
        StoredObjectRecord, on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    target_connection = models.ForeignKey(
        StorageConnection, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    target_bucket = models.ForeignKey(
        StorageBucket, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    target_key = models.CharField(max_length=700)
    target_version_id = models.CharField(max_length=240, blank=True)
    expected_sha256 = models.CharField(max_length=64)
    expected_size_bytes = models.BigIntegerField(validators=[MinValueValidator(0)])
    bytes_copied = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    state = models.CharField(max_length=16, choices=State.choices, default=State.PLANNED)
    client_request_id = models.CharField(max_length=160)
    delete_source_approved = models.BooleanField(default=False)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "client_request_id"],
                name="unique_storage_transfer_request_per_org",
            ),
            models.CheckConstraint(
                condition=models.Q(bytes_copied__lte=models.F("expected_size_bytes")),
                name="storage_transfer_progress_not_above_size",
            ),
        ]


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
    client_request_id = models.CharField(max_length=160, blank=True)
    leased_by = models.ForeignKey(
        "WorkerNode",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leased_jobs",
    )
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    review_reason = models.CharField(max_length=80, blank=True)
    review_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_wagvid_reviews",
    )
    review_priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["media", "revision"], name="unique_analysis_revision"),
            models.UniqueConstraint(
                fields=["organization", "client_request_id"],
                condition=~models.Q(client_request_id=""),
                name="unique_analysis_request_per_org",
            ),
        ]


class AnalysisResult(TimestampedModel):
    class State(models.TextChoices):
        DRAFT_AI = "draft-ai", "AI-kladde"
        NEEDS_REVIEW = "needs-review", "Kræver review"
        HUMAN_CONFIRMED = "human-confirmed", "Menneskeligt godkendt"
        PANEL_CONFIRMED = "panel-confirmed", "Panelgodkendt"
        FROZEN = "frozen", "Låst"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis_job = models.OneToOneField(
        AnalysisJob, on_delete=models.PROTECT, related_name="result"
    )
    state = models.CharField(max_length=24, choices=State.choices, default=State.DRAFT_AI)
    proposed_d_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    proposed_e_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    proposed_neutral = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    proposed_final_score = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    score_ledger = models.JSONField(default=dict)
    model_run = models.JSONField(default=dict)
    frozen_at = models.DateTimeField(null=True, blank=True)


class AnalysisProgressEvent(models.Model):
    """Append-only worker progress used by the UI and operational audit trail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analysis_job = models.ForeignKey(
        AnalysisJob, on_delete=models.CASCADE, related_name="progress_events"
    )
    sequence = models.PositiveIntegerField()
    stage = models.CharField(max_length=80)
    progress_percent = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    message = models.CharField(max_length=500, blank=True)
    worker = models.ForeignKey(
        "WorkerNode", on_delete=models.SET_NULL, null=True, related_name="progress_events"
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["analysis_job", "sequence"], name="unique_analysis_progress_sequence"
            )
        ]
        ordering = ["sequence"]

    def save(self, *args, **kwargs):
        if self.pk and AnalysisProgressEvent.objects.filter(pk=self.pk).exists():
            raise ValueError("Analysis progress events are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Analysis progress events are append-only")


class DeductionCandidate(TimestampedModel):
    class ReviewState(models.TextChoices):
        PENDING = "pending", "Afventer"
        ACCEPTED = "accepted", "Godkendt"
        REJECTED = "rejected", "Afvist"
        CORRECTED = "corrected", "Rettet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name="deductions")
    criterion = models.CharField(max_length=200)
    rule_reference = models.CharField(max_length=200)
    start_ms = models.PositiveIntegerField()
    end_ms = models.PositiveIntegerField()
    proposed_amount = models.DecimalField(max_digits=4, decimal_places=3)
    model_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    evidence = models.JSONField(default=dict)
    review_state = models.CharField(
        max_length=20, choices=ReviewState.choices, default=ReviewState.PENDING
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_ms__gte=models.F("start_ms")),
                name="deduction_time_range_valid",
            )
        ]


class ReviewDecision(models.Model):
    class Decision(models.TextChoices):
        ACCEPT_AI = "accept-ai", "AI-forslag godkendt"
        ACCEPT_OFFICIAL = "accept-official", "Officiel bedømmelse godkendt"
        CORRECT_AI = "correct-ai", "AI rettet"
        OFFICIAL_ERROR = "official-error", "Mulig officiel dommerfejl"
        INCONCLUSIVE = "inconclusive", "Utilstrækkelig evidens"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        DeductionCandidate, on_delete=models.PROTECT, related_name="decisions"
    )
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=24, choices=Decision.choices)
    accepted_amount = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ScoreComparisonReview(models.Model):
    class Decision(models.TextChoices):
        OFFICIAL_CONFIRMED = "official-confirmed", "Officielt resultat bekræftet"
        AI_DISCREPANCY_SUPPORTED = "ai-discrepancy", "AI-afvigelse bør undersøges"
        CORRECTED_LABELS = "corrected-labels", "Korrigerede læringsetiketter"
        INCONCLUSIVE = "inconclusive", "Utilstrækkelig evidens"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    result = models.ForeignKey(
        AnalysisResult, on_delete=models.PROTECT, related_name="score_reviews"
    )
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=24, choices=Decision.choices)
    accepted_d_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    accepted_e_score = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    accepted_neutral = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    accepted_final_score = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk and ScoreComparisonReview.objects.filter(pk=self.pk).exists():
            raise ValueError("Score comparison reviews are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Score comparison reviews are append-only")


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


class SystemBackup(TimestampedModel):
    class State(models.TextChoices):
        CREATED = "created", "Oprettet"
        VERIFYING = "verifying", "Verificerer"
        VERIFIED = "verified", "Verificeret"
        FAILED = "failed", "Fejlet"
        EXPIRED = "expired", "Udløbet"

    class Purpose(models.TextChoices):
        MANUAL = "manual", "Manuel"
        SCHEDULED = "scheduled", "Planlagt"
        PRE_UPGRADE = "pre-upgrade", "Før opgradering"
        PRE_MIGRATION = "pre-migration", "Før migrering"
        PRE_DESTRUCTIVE = "pre-destructive", "Før destruktiv handling"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=16, choices=State.choices, default=State.CREATED)
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    destination = models.CharField(max_length=300)
    retention_class = models.CharField(max_length=40, default="daily")
    application_release = models.CharField(max_length=80)
    git_sha = models.CharField(max_length=64)
    migration_heads = models.JSONField(default=list)
    manifest = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    verification = models.JSONField(default=dict)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)


class MaintenanceState(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    active = models.BooleanField(default=False)
    read_only = models.BooleanField(default=True)
    reason = models.CharField(max_length=300, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    entered_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class UpgradeJournal(TimestampedModel):
    class State(models.TextChoices):
        PLANNED = "planned", "Planlagt"
        BLOCKED = "blocked", "Blokeret"
        APPROVED = "approved", "Godkendt"
        RUNNING = "running", "Kører"
        VERIFYING = "verifying", "Verificerer"
        COMPLETED = "completed", "Færdig"
        FAILED = "failed", "Fejlet"
        ROLLBACK_STAGED = "rollback-staged", "Rollback klargjort"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_release = models.CharField(max_length=80)
    target_release = models.CharField(max_length=80)
    target_manifest = models.JSONField(default=dict)
    backup = models.ForeignKey(
        SystemBackup, on_delete=models.PROTECT, null=True, blank=True, related_name="upgrades"
    )
    state = models.CharField(max_length=24, choices=State.choices, default=State.PLANNED)
    preflight = models.JSONField(default=dict)
    migrations_planned = models.JSONField(default=list)
    config_migrations = models.JSONField(default=list)
    verification = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
