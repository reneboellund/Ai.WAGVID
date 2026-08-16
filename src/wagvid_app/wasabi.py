"""Pure Wasabi layout, routing, reconciliation and cost-policy planning."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

WASABI_REGION_ENDPOINTS = {
    "eu-central-1": "https://s3.eu-central-1.wasabisys.com",
    "eu-central-2": "https://s3.eu-central-2.wasabisys.com",
    "eu-west-1": "https://s3.eu-west-1.wasabisys.com",
    "eu-west-2": "https://s3.eu-west-2.wasabisys.com",
    "eu-west-3": "https://s3.eu-west-3.wasabisys.com",
    "eu-south-1": "https://s3.eu-south-1.wasabisys.com",
    "us-east-1": "https://s3.wasabisys.com",
    "us-east-2": "https://s3.us-east-2.wasabisys.com",
    "us-central-1": "https://s3.us-central-1.wasabisys.com",
    "us-west-1": "https://s3.us-west-1.wasabisys.com",
    "us-west-2": "https://s3.us-west-2.wasabisys.com",
    "ca-central-1": "https://s3.ca-central-1.wasabisys.com",
    "ap-northeast-1": "https://s3.ap-northeast-1.wasabisys.com",
    "ap-northeast-2": "https://s3.ap-northeast-2.wasabisys.com",
    "ap-southeast-1": "https://s3.ap-southeast-1.wasabisys.com",
    "ap-southeast-2": "https://s3.ap-southeast-2.wasabisys.com",
}


class BucketRole(StrEnum):
    ORIGINALS = "originals"
    DERIVATIVES = "derivatives"
    METADATA = "metadata"
    RESULTS = "results"
    AUDIT = "audit"


@dataclass(frozen=True)
class WasabiCostPolicy:
    pricing_model: str = "pay-go"
    minimum_storage_days: int = 90

    def __post_init__(self) -> None:
        if self.pricing_model not in {"pay-go", "rcs", "custom"}:
            raise ValueError("unsupported Wasabi pricing model")
        if self.minimum_storage_days < 1:
            raise ValueError("minimum storage duration must be positive")
        if self.pricing_model == "pay-go" and self.minimum_storage_days != 90:
            raise ValueError("Pay-Go must explicitly use Wasabi's 90-day default policy")
        if self.pricing_model == "rcs" and self.minimum_storage_days != 30:
            raise ValueError("RCS must explicitly use the 30-day minimum policy")

    def billable_until(self, uploaded_at: datetime) -> datetime:
        if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
            raise ValueError("upload timestamp must be timezone-aware")
        return uploaded_at.astimezone(UTC) + timedelta(days=self.minimum_storage_days)

    def early_delete_exposure_gb_days(
        self, *, size_bytes: int, uploaded_at: datetime, delete_at: datetime,
    ) -> float:
        if size_bytes < 0 or delete_at.tzinfo is None or delete_at.utcoffset() is None:
            raise ValueError("size and deletion timestamp are invalid")
        remaining = max(0.0, (self.billable_until(uploaded_at) - delete_at).total_seconds() / 86400)
        return size_bytes / 1_000_000_000 * remaining


@dataclass(frozen=True)
class WasabiLayoutConfig:
    project_slug: str
    environment: str
    account_fingerprint: str
    region: str
    originals_shards: int = 2
    derivatives_shards: int = 2
    include_audit_bucket: bool = True
    enable_versioning: bool = True
    endpoint_override: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,20}", self.project_slug):
            raise ValueError("project slug must be lowercase DNS-safe text")
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,12}", self.environment):
            raise ValueError("environment must be lowercase DNS-safe text")
        if not re.fullmatch(r"[a-f0-9]{8,16}", self.account_fingerprint):
            raise ValueError("account fingerprint must be 8-16 lowercase hexadecimal characters")
        if self.region not in WASABI_REGION_ENDPOINTS and not self.endpoint_override:
            raise ValueError("unknown Wasabi region requires explicit endpoint override")
        if not 1 <= self.originals_shards <= 32 or not 1 <= self.derivatives_shards <= 32:
            raise ValueError("bucket shard counts must be between 1 and 32")

    @property
    def endpoint(self) -> str:
        return self.endpoint_override or WASABI_REGION_ENDPOINTS[self.region]


@dataclass(frozen=True)
class DesiredBucket:
    name: str
    role: BucketRole
    shard: int
    region: str
    private: bool
    versioning: bool
    object_lock: bool


@dataclass(frozen=True)
class WasabiSetupPlan:
    endpoint: str
    region: str
    buckets: tuple[DesiredBucket, ...]
    cost_policy: WasabiCostPolicy
    warnings: tuple[str, ...]

    @property
    def digest(self) -> str:
        value = {
            "endpoint": self.endpoint,
            "region": self.region,
            "buckets": [
                {
                    "name": item.name, "role": item.role.value, "shard": item.shard,
                    "region": item.region, "private": item.private,
                    "versioning": item.versioning, "object_lock": item.object_lock,
                }
                for item in self.buckets
            ],
            "cost_policy": {
                "pricing_model": self.cost_policy.pricing_model,
                "minimum_storage_days": self.cost_policy.minimum_storage_days,
            },
            "warnings": self.warnings,
        }
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def build_setup_plan(
    config: WasabiLayoutConfig, cost_policy: WasabiCostPolicy,
) -> WasabiSetupPlan:
    pools = {
        BucketRole.ORIGINALS: config.originals_shards,
        BucketRole.DERIVATIVES: config.derivatives_shards,
        BucketRole.METADATA: 1,
        BucketRole.RESULTS: 1,
    }
    if config.include_audit_bucket:
        pools[BucketRole.AUDIT] = 1
    buckets = []
    for role, count in pools.items():
        for shard in range(count):
            suffix = f"-{shard + 1:02d}" if count > 1 else ""
            name = (
                f"{config.project_slug}-{config.environment}-{role.value}"
                f"{suffix}-{config.account_fingerprint}"
            )
            if len(name) > 63:
                raise ValueError(f"generated bucket name exceeds 63 characters: {name}")
            buckets.append(DesiredBucket(
                name, role, shard, config.region, True, config.enable_versioning,
                role in {BucketRole.ORIGINALS, BucketRole.AUDIT},
            ))
    return WasabiSetupPlan(
        config.endpoint, config.region, tuple(buckets), cost_policy,
        (
            "Physical deletion before billable_until may incur Timed Deleted Storage",
            "Transient frames and cache must not use minimum-duration Wasabi storage",
            "Bucket creation and policy changes require explicit administrator approval",
        ),
    )


def route_object(
    *, role: BucketRole, routing_key: str, buckets: tuple[DesiredBucket, ...],
) -> DesiredBucket:
    candidates = [bucket for bucket in buckets if bucket.role is role]
    if not candidates or not routing_key:
        raise ValueError("routing requires a key and at least one bucket for the role")
    # Rendezvous hashing minimizes movement when the versioned pool is expanded.
    return max(
        candidates,
        key=lambda bucket: hashlib.sha256(f"{routing_key}|{bucket.name}".encode()).digest(),
    )


@dataclass(frozen=True)
class ReconcileAction:
    action: str
    bucket: str
    details: dict[str, Any]
    destructive: bool = False


def reconcile_plan(
    desired: WasabiSetupPlan, discovered: dict[str, dict[str, Any]],
) -> tuple[ReconcileAction, ...]:
    actions: list[ReconcileAction] = []
    for bucket in desired.buckets:
        actual = discovered.get(bucket.name)
        if not actual:
            actions.append(ReconcileAction(
                "create-private-bucket", bucket.name,
                {"region": bucket.region, "object_lock": bucket.object_lock},
            ))
            if bucket.versioning:
                actions.append(ReconcileAction("enable-versioning", bucket.name, {}))
            continue
        if actual.get("region") != bucket.region:
            actions.append(ReconcileAction(
                "block-region-conflict", bucket.name,
                {"expected": bucket.region, "actual": actual.get("region")}, True,
            ))
        if actual.get("public") is True:
            actions.append(ReconcileAction("block-public-bucket", bucket.name, {}, True))
        if bucket.versioning and actual.get("versioning") != "Enabled":
            actions.append(ReconcileAction("enable-versioning", bucket.name, {}))
    return tuple(actions)
