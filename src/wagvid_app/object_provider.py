"""Provider-neutral object-storage contracts and S3 capability model.

The existing LocalObjectStore and Wasabi implementation remain valid. This module is
the boundary used to add AWS S3, ONTAP S3, VAST and validated Ootbi without leaking
provider assumptions into media/capture domain code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import BinaryIO, Protocol, runtime_checkable

from .storage import StoredObject


class ProviderType(StrEnum):
    LOCAL = "local"
    WASABI = "wasabi"
    AWS_S3 = "aws-s3"
    ONTAP_S3 = "ontap-s3"
    VAST_S3 = "vast-s3"
    OOTBI_S3 = "ootbi-s3"
    GENERIC_S3 = "generic-s3"


class StorageFeature(StrEnum):
    RANGE_GET = "range-get"
    MULTIPART = "multipart"
    PRESIGNED_GET = "presigned-get"
    PRESIGNED_PUT = "presigned-put"
    VERSIONING = "versioning"
    OBJECT_LOCK = "object-lock"
    LEGAL_HOLD = "legal-hold"
    LIFECYCLE = "lifecycle"
    BUCKET_POLICY = "bucket-policy"
    PUBLIC_ACCESS_BLOCK = "public-access-block"
    SERVER_SIDE_ENCRYPTION = "server-side-encryption"
    BUCKET_PROVISIONING = "bucket-provisioning"
    CAPACITY_METRICS = "capacity-metrics"


@dataclass(frozen=True)
class StorageCapabilities:
    features: frozenset[StorageFeature] = frozenset()
    notes: tuple[str, ...] = ()
    max_object_size_bytes: int | None = None

    def supports(self, feature: StorageFeature) -> bool:
        return feature in self.features

    def require(self, *features: StorageFeature) -> tuple[StorageFeature, ...]:
        return tuple(feature for feature in features if feature not in self.features)


@dataclass(frozen=True)
class StorageConnectionProfile:
    provider_id: str
    provider_type: ProviderType
    endpoint: str | None = None
    region: str | None = None
    credential_ref: str | None = None
    ca_bundle_ref: str | None = None
    addressing_style: str = "auto"
    tls_required: bool = True
    logical_roles: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.provider_id.strip():
            raise ValueError("provider_id is required")
        if self.credential_ref:
            lowered = self.credential_ref.casefold()
            if "secret=" in lowered or "password=" in lowered:
                raise ValueError("credential_ref must reference secret storage, not contain a secret")
        if self.addressing_style not in {"auto", "virtual", "path"}:
            raise ValueError("addressing_style must be auto, virtual or path")


@dataclass(frozen=True)
class ObjectLocation:
    provider_id: str
    bucket: str
    key: str
    version_id: str | None = None

    def __post_init__(self):
        if not self.provider_id or not self.bucket or not self.key:
            raise ValueError("provider_id, bucket and key are required")
        if self.key.startswith("/") or ".." in self.key.split("/"):
            raise ValueError("Unsafe object key")


@dataclass(frozen=True)
class StoragePreflight:
    connected: bool
    capabilities: StorageCapabilities
    identity_summary: str | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.connected and not self.blockers


@dataclass(frozen=True)
class GovernanceRequirement:
    required_features: frozenset[StorageFeature] = frozenset()
    require_tls: bool = True
    require_immutable_originals: bool = False


def evaluate_governance(
    profile: StorageConnectionProfile,
    preflight: StoragePreflight,
    requirement: GovernanceRequirement,
) -> tuple[str, ...]:
    blockers = list(preflight.blockers)
    if not preflight.connected:
        blockers.append("provider-unreachable")
    if requirement.require_tls and not profile.tls_required:
        blockers.append("tls-required")
    missing = preflight.capabilities.require(*sorted(requirement.required_features, key=str))
    blockers.extend(f"missing-capability:{feature.value}" for feature in missing)
    if requirement.require_immutable_originals and not (
        preflight.capabilities.supports(StorageFeature.OBJECT_LOCK)
        or preflight.capabilities.supports(StorageFeature.VERSIONING)
    ):
        blockers.append("immutable-originals-unavailable")
    return tuple(dict.fromkeys(blockers))


@runtime_checkable
class ObjectStorageProvider(Protocol):
    """Minimal data-plane contract used by Ai.WAGVID media operations."""

    provider_id: str

    def preflight(self) -> StoragePreflight: ...

    def put_verified(
        self, location: ObjectLocation, source: BinaryIO, *, expected_size: int, expected_sha256: str
    ) -> StoredObject: ...

    def inspect(self, location: ObjectLocation) -> StoredObject: ...

    def open_read(self, location: ObjectLocation) -> BinaryIO: ...
