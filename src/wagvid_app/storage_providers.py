"""Provider-neutral object-storage capability and governance catalogue."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PROBE = "probe-required"


class StorageCapability(StrEnum):
    SIGV4 = "sigv4"
    RANGE_GET = "range-get"
    MULTIPART = "multipart"
    PRESIGNED_GET = "presigned-get"
    VERSIONING = "versioning"
    OBJECT_LOCK = "object-lock"
    LIFECYCLE = "lifecycle"
    SSE_S3 = "sse-s3"
    CHECKSUM_SHA256 = "checksum-sha256"
    BUCKET_PROVISIONING = "bucket-provisioning"
    PUBLIC_ACCESS_INSPECTION = "public-access-inspection"
    WORKLOAD_IDENTITY = "workload-identity"


class GovernanceProfile(StrEnum):
    STANDARD = "standard"
    EVIDENCE = "evidence-immutable"
    BACKUP_TARGET = "backup-target"


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    label: str
    cloud: bool
    default_addressing_style: str
    default_region: str
    existing_bucket_only: bool
    conditional_support: bool
    capabilities: Mapping[StorageCapability, CapabilityState]
    notes: tuple[str, ...] = ()

    def snapshot(self) -> dict:
        value = asdict(self)
        value["capabilities"] = {key.value: state.value for key, state in self.capabilities.items()}
        return value


@dataclass(frozen=True)
class ObjectLocation:
    provider_id: str
    connection_id: str
    bucket: str
    key: str
    version_id: str = ""


def _caps(**overrides: CapabilityState) -> Mapping[StorageCapability, CapabilityState]:
    values = {capability: CapabilityState.PROBE for capability in StorageCapability}
    for key, value in overrides.items():
        values[StorageCapability(key.replace("_", "-"))] = value
    return MappingProxyType(values)


PROVIDERS: Mapping[str, ProviderDefinition] = MappingProxyType(
    {
        "wasabi": ProviderDefinition(
            "wasabi", "Wasabi", True, "virtual", "eu-central-1", False, False,
            _caps(
                sigv4=CapabilityState.SUPPORTED,
                range_get=CapabilityState.SUPPORTED,
                multipart=CapabilityState.SUPPORTED,
                presigned_get=CapabilityState.SUPPORTED,
                versioning=CapabilityState.SUPPORTED,
                object_lock=CapabilityState.SUPPORTED,
                sse_s3=CapabilityState.SUPPORTED,
                checksum_sha256=CapabilityState.SUPPORTED,
                bucket_provisioning=CapabilityState.SUPPORTED,
                public_access_inspection=CapabilityState.SUPPORTED,
                workload_identity=CapabilityState.UNSUPPORTED,
            ),
            ("Pay-Go objects normally have a 90-day minimum billing duration.",),
        ),
        "aws-s3": ProviderDefinition(
            "aws-s3", "Amazon S3", True, "virtual", "eu-central-1", False, False,
            _caps(**{capability.value.replace("-", "_"): CapabilityState.SUPPORTED for capability in StorageCapability}),
            ("Prefer IAM role, workload identity or STS over long-lived keys.",),
        ),
        "ontap-s3": ProviderDefinition(
            "ontap-s3", "NetApp ONTAP S3", False, "path", "us-east-1", False, False,
            _caps(
                sigv4=CapabilityState.SUPPORTED,
                range_get=CapabilityState.SUPPORTED,
                multipart=CapabilityState.SUPPORTED,
                workload_identity=CapabilityState.UNSUPPORTED,
            ),
            ("Versioning and Object Lock depend on the ONTAP release and bucket configuration.",),
        ),
        "vast-s3": ProviderDefinition(
            "vast-s3", "VAST Data S3", False, "path", "us-east-1", False, False,
            _caps(
                sigv4=CapabilityState.SUPPORTED,
                range_get=CapabilityState.SUPPORTED,
                multipart=CapabilityState.SUPPORTED,
                workload_identity=CapabilityState.UNSUPPORTED,
            ),
            ("S3 identity is canonical; no POSIX/NFS path equivalence is inferred.",),
        ),
        "ootbi-s3": ProviderDefinition(
            "ootbi-s3", "Object First Ootbi", False, "path", "us-east-1", True, True,
            _caps(
                sigv4=CapabilityState.PROBE,
                range_get=CapabilityState.PROBE,
                multipart=CapabilityState.PROBE,
                bucket_provisioning=CapabilityState.UNSUPPORTED,
                lifecycle=CapabilityState.UNSUPPORTED,
                workload_identity=CapabilityState.UNSUPPORTED,
            ),
            (
                "Production support requires a dedicated-appliance contract validation.",
                "Derivatives and transient cache roles are disabled by default.",
            ),
        ),
    }
)


GOVERNANCE_REQUIREMENTS = MappingProxyType(
    {
        GovernanceProfile.STANDARD: frozenset(
            {StorageCapability.SIGV4, StorageCapability.RANGE_GET, StorageCapability.MULTIPART}
        ),
        GovernanceProfile.EVIDENCE: frozenset(
            {
                StorageCapability.SIGV4,
                StorageCapability.RANGE_GET,
                StorageCapability.MULTIPART,
                StorageCapability.VERSIONING,
                StorageCapability.OBJECT_LOCK,
            }
        ),
        GovernanceProfile.BACKUP_TARGET: frozenset(
            {StorageCapability.SIGV4, StorageCapability.MULTIPART}
        ),
    }
)


def provider_definition(provider_id: str) -> ProviderDefinition:
    try:
        return PROVIDERS[provider_id]
    except KeyError as error:
        raise ValueError(f"unknown object-storage provider: {provider_id}") from error


def evaluate_capabilities(
    provider_id: str,
    governance_profile: str,
    verified: Mapping[str, str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    definition = provider_definition(provider_id)
    try:
        requirements = GOVERNANCE_REQUIREMENTS[GovernanceProfile(governance_profile)]
    except (KeyError, ValueError) as error:
        raise ValueError(f"unknown governance profile: {governance_profile}") from error
    observed = dict(verified or {})
    blockers = []
    unresolved = []
    for capability in requirements:
        state = CapabilityState(
            observed.get(capability.value, definition.capabilities[capability].value)
        )
        if state is CapabilityState.UNSUPPORTED:
            blockers.append(f"required capability unsupported: {capability.value}")
        elif state is CapabilityState.PROBE:
            unresolved.append(f"required capability not validated: {capability.value}")
    if blockers:
        return "incompatible", tuple(sorted(blockers + unresolved))
    if unresolved or definition.conditional_support:
        return "limited", tuple(sorted(unresolved))
    return "validated", ()
