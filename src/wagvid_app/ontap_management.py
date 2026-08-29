"""Pure ONTAP management capability and dry-run planning.

Actual REST transport is intentionally separate. These contracts let the admin UI build
an idempotent, approval-gated plan before any ONTAP mutation occurs. Version gates are
based on NetApp's documented ONTAP S3 feature introductions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import Mapping


@total_ordering
@dataclass(frozen=True)
class OntapVersion:
    major: int
    minor: int
    patch: int = 0

    @classmethod
    def parse(cls, value: str) -> "OntapVersion":
        text = value.strip().removeprefix("ONTAP ")
        parts = text.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid ONTAP version: {value}")
        try:
            numbers = [int(part) for part in parts[:3]]
        except ValueError as exc:
            raise ValueError(f"Invalid ONTAP version: {value}") from exc
        while len(numbers) < 3:
            numbers.append(0)
        return cls(*numbers)

    def __lt__(self, other):
        if not isinstance(other, OntapVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class OntapFeature(StrEnum):
    NATIVE_S3 = "native-s3"
    S3_AUDIT = "s3-audit"
    SNAPMIRROR_S3 = "snapmirror-s3"
    OBJECT_VERSIONING = "object-versioning"
    PRESIGNED_URLS = "presigned-urls"
    BUCKET_POLICY = "bucket-policy"
    LIFECYCLE = "lifecycle"
    OBJECT_LOCK = "object-lock"
    S3_SNAPSHOTS = "s3-snapshots"


FEATURE_MIN_VERSION = {
    OntapFeature.NATIVE_S3: OntapVersion(9, 8, 0),
    OntapFeature.S3_AUDIT: OntapVersion(9, 10, 1),
    OntapFeature.SNAPMIRROR_S3: OntapVersion(9, 10, 1),
    OntapFeature.OBJECT_VERSIONING: OntapVersion(9, 11, 1),
    OntapFeature.PRESIGNED_URLS: OntapVersion(9, 11, 1),
    OntapFeature.BUCKET_POLICY: OntapVersion(9, 12, 1),
    OntapFeature.LIFECYCLE: OntapVersion(9, 13, 1),
    OntapFeature.OBJECT_LOCK: OntapVersion(9, 14, 1),
    OntapFeature.S3_SNAPSHOTS: OntapVersion(9, 16, 1),
}


@dataclass(frozen=True)
class OntapCapabilities:
    version: OntapVersion
    native_s3: bool = True
    s3_nas: bool = False
    metrocluster: bool = False

    @property
    def features(self) -> frozenset[OntapFeature]:
        if not self.native_s3:
            return frozenset()
        if self.s3_nas:
            # S3 NAS does not support native S3 versioning/Object Lock/lifecycle/S3 snapshots.
            return frozenset({OntapFeature.NATIVE_S3})
        available = {
            feature
            for feature, minimum in FEATURE_MIN_VERSION.items()
            if self.version >= minimum
        }
        if self.metrocluster:
            available.discard(OntapFeature.SNAPMIRROR_S3)
        return frozenset(available)

    def supports(self, feature: OntapFeature) -> bool:
        return feature in self.features


@dataclass(frozen=True)
class OntapBucketState:
    name: str
    uuid: str | None = None
    versioning_state: str = "disabled"
    retention_mode: str = "no_lock"
    snapshot_policy: str | None = None


@dataclass(frozen=True)
class OntapDiscovery:
    version: OntapVersion
    svm_uuid: str
    svm_name: str
    s3_service_exists: bool
    user_names: frozenset[str]
    group_names: frozenset[str]
    buckets: Mapping[str, OntapBucketState]
    native_s3: bool = True
    s3_nas: bool = False
    metrocluster: bool = False

    @property
    def capabilities(self) -> OntapCapabilities:
        return OntapCapabilities(
            self.version,
            native_s3=self.native_s3,
            s3_nas=self.s3_nas,
            metrocluster=self.metrocluster,
        )


@dataclass(frozen=True)
class OntapDesiredBucket:
    role: str
    name: str
    versioning: bool = False
    retention_mode: str = "no_lock"
    retention_days: int | None = None
    snapshot_policy: str | None = None
    lifecycle_expire_days: int | None = None

    def __post_init__(self):
        if self.retention_mode not in {"no_lock", "governance", "compliance"}:
            raise ValueError("Unsupported ONTAP retention mode")
        if self.retention_mode != "no_lock" and not self.retention_days:
            raise ValueError("Object Lock retention requires retention_days")
        if self.retention_days is not None and self.retention_days < 1:
            raise ValueError("retention_days must be positive")
        if self.lifecycle_expire_days is not None and self.lifecycle_expire_days < 1:
            raise ValueError("lifecycle_expire_days must be positive")


@dataclass(frozen=True)
class OntapDesiredLayout:
    s3_user_name: str
    s3_group_name: str
    buckets: tuple[OntapDesiredBucket, ...]
    audit_required: bool = False


@dataclass(frozen=True)
class OntapAction:
    action: str
    endpoint: str
    payload: dict
    reason: str
    required_feature: OntapFeature | None = None
    destructive: bool = False


@dataclass(frozen=True)
class OntapPlan:
    actions: tuple[OntapAction, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def applicable(self) -> bool:
        return not self.blockers and not any(action.destructive for action in self.actions)


def _retention_payload(target: OntapDesiredBucket) -> dict | None:
    if target.retention_mode == "no_lock":
        return None
    return {
        "mode": target.retention_mode,
        "default_period": f"P{target.retention_days}D",
    }


def plan_ontap_setup(discovery: OntapDiscovery, desired: OntapDesiredLayout) -> OntapPlan:
    capabilities = discovery.capabilities
    actions: list[OntapAction] = []
    blockers: list[str] = []
    warnings: list[str] = []

    if not capabilities.supports(OntapFeature.NATIVE_S3):
        return OntapPlan((), ("native-ontap-s3-unavailable",), ())
    if discovery.s3_nas:
        return OntapPlan((), ("native-s3-required-for-managed-bucket-protection",), ())

    svm_path = f"/api/protocols/s3/services/{discovery.svm_uuid}"
    if not discovery.s3_service_exists:
        actions.append(
            OntapAction(
                "create-s3-service",
                "/api/protocols/s3/services",
                {"svm": {"uuid": discovery.svm_uuid}, "enabled": True},
                "SVM has no S3 service",
            )
        )
    if desired.s3_user_name not in discovery.user_names:
        actions.append(
            OntapAction(
                "create-s3-user",
                f"{svm_path}/users",
                {"name": desired.s3_user_name},
                "Dedicated Ai.WAGVID S3 user is missing",
            )
        )
    if desired.s3_group_name not in discovery.group_names:
        actions.append(
            OntapAction(
                "create-s3-group",
                f"{svm_path}/groups",
                {"name": desired.s3_group_name, "users": [desired.s3_user_name]},
                "Least-privilege Ai.WAGVID S3 group is missing",
            )
        )

    for target in sorted(desired.buckets, key=lambda item: (item.role, item.name)):
        locked = target.retention_mode != "no_lock"
        if locked and not capabilities.supports(OntapFeature.OBJECT_LOCK):
            blockers.append(f"{target.name}:object-lock-requires-ontap-9.14.1+")
        if target.versioning and not capabilities.supports(OntapFeature.OBJECT_VERSIONING):
            blockers.append(f"{target.name}:versioning-requires-ontap-9.11.1+")
        if target.snapshot_policy and not capabilities.supports(OntapFeature.S3_SNAPSHOTS):
            blockers.append(f"{target.name}:s3-snapshots-require-ontap-9.16.1+")
        if target.lifecycle_expire_days is not None and not capabilities.supports(
            OntapFeature.LIFECYCLE
        ):
            blockers.append(f"{target.name}:lifecycle-requires-ontap-9.13.1+")

        existing = discovery.buckets.get(target.name)
        if existing is None:
            payload: dict = {"name": target.name, "type": "s3"}
            if target.versioning:
                payload["versioning_state"] = "enabled"
            retention = _retention_payload(target)
            if retention:
                payload["retention"] = retention
            if target.snapshot_policy:
                payload["snapshot_policy"] = {"name": target.snapshot_policy}
            actions.append(
                OntapAction(
                    "create-bucket",
                    f"{svm_path}/buckets",
                    payload,
                    f"Create native S3 bucket for logical role {target.role}",
                )
            )
            # Desired state is applied at creation; do not create duplicate PATCH actions.
            existing = OntapBucketState(
                target.name,
                versioning_state="enabled" if target.versioning else "disabled",
                retention_mode=target.retention_mode,
                snapshot_policy=target.snapshot_policy,
            )

        if target.versioning and existing.versioning_state != "enabled":
            actions.append(
                OntapAction(
                    "enable-versioning",
                    f"{svm_path}/buckets/{existing.uuid or target.name}",
                    {"versioning_state": "enabled"},
                    "Evidence/data policy requests object versioning",
                    OntapFeature.OBJECT_VERSIONING,
                )
            )
        if locked and existing.retention_mode == "no_lock" and existing.uuid:
            # Retention/Object Lock is a bucket creation decision. Do not offer an unsafe
            # in-place conversion that ONTAP cannot guarantee.
            blockers.append(f"{target.name}:object-lock-cannot-be-enabled-after-bucket-creation")
        if target.snapshot_policy and existing.snapshot_policy != target.snapshot_policy:
            actions.append(
                OntapAction(
                    "assign-snapshot-policy",
                    f"{svm_path}/buckets/{existing.uuid or target.name}",
                    {"snapshot_policy": {"name": target.snapshot_policy}},
                    "Assign S3 snapshot protection policy",
                    OntapFeature.S3_SNAPSHOTS,
                )
            )
        if target.lifecycle_expire_days is not None:
            actions.append(
                OntapAction(
                    "ensure-lifecycle-rule",
                    f"{svm_path}/buckets/{existing.uuid or target.name}/rules",
                    {
                        "name": "ai-wagvid-expiration",
                        "enabled": True,
                        "expiration": {"object_age_days": target.lifecycle_expire_days},
                    },
                    "Expire transient derived data according to configured retention",
                    OntapFeature.LIFECYCLE,
                )
            )

    if desired.audit_required:
        if capabilities.supports(OntapFeature.S3_AUDIT):
            actions.append(
                OntapAction(
                    "ensure-s3-audit",
                    f"/api/protocols/audit/{discovery.svm_uuid}/object-store",
                    {"enabled": True, "format": "json"},
                    "Governance profile requires ONTAP S3 audit",
                    OntapFeature.S3_AUDIT,
                )
            )
        else:
            blockers.append("s3-audit-requires-ontap-9.10.1+")

    if discovery.metrocluster:
        warnings.append("SnapMirror S3 is unavailable in MetroCluster configurations")
    return OntapPlan(tuple(actions), tuple(dict.fromkeys(blockers)), tuple(warnings))


def plan_snapmirror_s3(
    discovery: OntapDiscovery,
    *,
    source_bucket: str,
    destination: str,
    policy: str = "Continuous",
) -> OntapPlan:
    if not discovery.capabilities.supports(OntapFeature.SNAPMIRROR_S3):
        return OntapPlan((), ("snapmirror-s3-unavailable",), ())
    if source_bucket not in discovery.buckets:
        return OntapPlan((), (f"unknown-source-bucket:{source_bucket}",), ())
    action = OntapAction(
        "create-snapmirror-s3",
        "/api/snapmirror/relationships",
        {
            "source": {"path": f"{discovery.svm_name}:{source_bucket}"},
            "destination": {"path": destination},
            "policy": {"name": policy},
        },
        "Create approved S3 protection relationship",
        OntapFeature.SNAPMIRROR_S3,
    )
    return OntapPlan((action,), (), ())
