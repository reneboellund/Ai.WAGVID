"""Provider-neutral bounded bucket layout and cost policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .storage_providers import ProviderDefinition
from .storage_types import BucketRole, DesiredBucket


@dataclass(frozen=True)
class StorageCostPolicy:
    pricing_model: str
    minimum_storage_days: int

    def __post_init__(self) -> None:
        if self.pricing_model not in {"none", "pay-go", "rcs", "custom"}:
            raise ValueError("unsupported storage pricing model")
        if self.minimum_storage_days < 0:
            raise ValueError("minimum storage duration cannot be negative")
        if self.pricing_model == "none" and self.minimum_storage_days != 0:
            raise ValueError("no-minimum pricing must use zero minimum days")
        if self.pricing_model == "pay-go" and self.minimum_storage_days != 90:
            raise ValueError("Wasabi Pay-Go requires 90 minimum days")
        if self.pricing_model == "rcs" and self.minimum_storage_days != 30:
            raise ValueError("Wasabi RCS requires 30 minimum days")

    def billable_until(self, uploaded_at: datetime) -> datetime:
        if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
            raise ValueError("upload timestamp must be timezone-aware")
        return uploaded_at.astimezone(UTC) + timedelta(days=self.minimum_storage_days)

    def early_delete_exposure_gb_days(
        self, *, size_bytes: int, uploaded_at: datetime, delete_at: datetime
    ) -> float:
        if size_bytes < 0 or delete_at.tzinfo is None or delete_at.utcoffset() is None:
            raise ValueError("size and deletion timestamp are invalid")
        remaining = max(0.0, (self.billable_until(uploaded_at) - delete_at).total_seconds() / 86400)
        return size_bytes / 1_000_000_000 * remaining


@dataclass(frozen=True)
class StorageLayoutPlan:
    provider_id: str
    endpoint: str
    region: str
    buckets: tuple[DesiredBucket, ...]
    cost_policy: StorageCostPolicy
    warnings: tuple[str, ...]
    provisioning_enabled: bool

    @property
    def digest(self) -> str:
        value = {
            "provider_id": self.provider_id,
            "endpoint": self.endpoint,
            "region": self.region,
            "buckets": [
                {
                    "name": item.name,
                    "role": item.role.value,
                    "shard": item.shard,
                    "region": item.region,
                    "private": item.private,
                    "versioning": item.versioning,
                    "object_lock": item.object_lock,
                }
                for item in self.buckets
            ],
            "cost_policy": {
                "pricing_model": self.cost_policy.pricing_model,
                "minimum_storage_days": self.cost_policy.minimum_storage_days,
            },
            "warnings": self.warnings,
            "provisioning_enabled": self.provisioning_enabled,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _mapped_names(connection, role: BucketRole, count: int) -> tuple[str, ...]:
    configured = connection.existing_bucket_map.get(role.value, [])
    if isinstance(configured, str):
        configured = [configured]
    if configured:
        if len(configured) != count:
            raise ValueError(f"bucket mapping for {role.value} must contain {count} entries")
        return tuple(configured)
    names = []
    for shard in range(count):
        suffix = f"-{shard + 1:02d}" if count > 1 else ""
        names.append(
            f"{connection.project_slug}-{connection.environment}-{role.value}"
            f"{suffix}-{connection.account_fingerprint}"
        )
    return tuple(names)


def build_storage_layout(connection, definition: ProviderDefinition) -> StorageLayoutPlan:
    pools = {
        BucketRole.ORIGINALS: connection.originals_shards,
        BucketRole.DERIVATIVES: connection.derivatives_shards,
        BucketRole.METADATA: 1,
        BucketRole.RESULTS: 1,
    }
    if connection.include_audit_bucket:
        pools[BucketRole.AUDIT] = 1
    if definition.provider_id == "ootbi-s3" and not connection.existing_bucket_map:
        raise ValueError("Ootbi requires explicit existing bucket mappings")
    buckets = []
    for role, count in pools.items():
        if definition.provider_id == "ootbi-s3" and (
            role is BucketRole.DERIVATIVES or role.value not in connection.existing_bucket_map
        ):
            continue
        for shard, name in enumerate(_mapped_names(connection, role, count)):
            if len(name) > 63 or not name:
                raise ValueError(f"invalid S3 bucket name: {name}")
            buckets.append(
                DesiredBucket(
                    name,
                    role,
                    shard,
                    connection.region,
                    True,
                    connection.enable_versioning,
                    connection.governance_profile == "evidence-immutable"
                    and role in {BucketRole.ORIGINALS, BucketRole.AUDIT},
                )
            )
    if definition.provider_id == "ootbi-s3" and not any(
        item.role in {BucketRole.ORIGINALS, BucketRole.AUDIT} for item in buckets
    ):
        raise ValueError("Ootbi mapping requires an originals or audit bucket")
    warnings = list(definition.notes)
    if not connection.tls_verify:
        warnings.append("TLS verification is disabled; this is allowed only in explicit lab use")
    if connection.custom_ca_secret_ref:
        warnings.append("A custom CA reference must be resolved by the runtime client factory")
    return StorageLayoutPlan(
        definition.provider_id,
        connection.endpoint,
        connection.region,
        tuple(buckets),
        StorageCostPolicy(connection.pricing_model, connection.minimum_storage_days),
        tuple(warnings),
        connection.provisioning_enabled and not definition.existing_bucket_only,
    )
