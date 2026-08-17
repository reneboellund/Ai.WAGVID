"""Generic S3-compatible preflight helpers.

The probe is intentionally conservative: a capability is only advertised after the
configured endpoint/client demonstrates it or an adapter supplies validated evidence.
Provider-specific control-plane code (ONTAP, VAST, Ootbi, AWS) can enrich this result.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Protocol

from .object_provider import (
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)


class S3ProviderError(RuntimeError):
    pass


class S3InspectionClient(Protocol):
    def head_bucket(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_object_lock_configuration(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_policy(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_public_access_block(self, *, Bucket: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BucketProbe:
    bucket: str
    reachable: bool
    features: frozenset[StorageFeature]
    versioning_state: str | None = None
    object_lock_enabled: bool | None = None
    warnings: tuple[str, ...] = ()


def _attempt(call, *args, **kwargs):
    try:
        return True, call(*args, **kwargs), None
    except Exception as error:  # noqa: BLE001 - SDK/provider exception classes are optional
        return False, None, type(error).__name__


def inspect_bucket(client: S3InspectionClient, bucket: str) -> BucketProbe:
    reachable, _, head_error = _attempt(client.head_bucket, Bucket=bucket)
    if not reachable:
        return BucketProbe(
            bucket=bucket,
            reachable=False,
            features=frozenset(),
            warnings=(f"head-bucket:{head_error}",),
        )

    features = {StorageFeature.RANGE_GET, StorageFeature.MULTIPART}
    warnings: list[str] = []
    versioning_state = None
    object_lock_enabled = None

    ok, value, error = _attempt(client.get_bucket_versioning, Bucket=bucket)
    if ok:
        features.add(StorageFeature.VERSIONING)
        versioning_state = str((value or {}).get("Status") or "Disabled")
    else:
        warnings.append(f"versioning-unverified:{error}")

    ok, value, error = _attempt(client.get_object_lock_configuration, Bucket=bucket)
    if ok:
        features.add(StorageFeature.OBJECT_LOCK)
        configuration = (value or {}).get("ObjectLockConfiguration", {})
        object_lock_enabled = configuration.get("ObjectLockEnabled") == "Enabled"
        if object_lock_enabled:
            features.add(StorageFeature.LEGAL_HOLD)
    else:
        warnings.append(f"object-lock-unverified:{error}")

    ok, _, error = _attempt(client.get_bucket_lifecycle_configuration, Bucket=bucket)
    if ok:
        features.add(StorageFeature.LIFECYCLE)
    else:
        warnings.append(f"lifecycle-unverified:{error}")

    ok, _, error = _attempt(client.get_bucket_policy, Bucket=bucket)
    if ok:
        features.add(StorageFeature.BUCKET_POLICY)
    else:
        warnings.append(f"bucket-policy-unverified:{error}")

    ok, _, error = _attempt(client.get_public_access_block, Bucket=bucket)
    if ok:
        features.add(StorageFeature.PUBLIC_ACCESS_BLOCK)
    else:
        warnings.append(f"public-access-block-unverified:{error}")

    return BucketProbe(
        bucket=bucket,
        reachable=True,
        features=frozenset(features),
        versioning_state=versioning_state,
        object_lock_enabled=object_lock_enabled,
        warnings=tuple(warnings),
    )


def preflight_existing_buckets(
    profile: StorageConnectionProfile,
    client: S3InspectionClient,
    *,
    buckets: list[str],
    extra_verified_features: frozenset[StorageFeature] = frozenset(),
) -> tuple[StoragePreflight, tuple[BucketProbe, ...]]:
    probes = tuple(inspect_bucket(client, bucket) for bucket in sorted(set(buckets)))
    reachable = [probe for probe in probes if probe.reachable]
    blockers = tuple(
        f"bucket-unreachable:{probe.bucket}" for probe in probes if not probe.reachable
    )
    common_features: set[StorageFeature] = set(extra_verified_features)
    if reachable:
        common_features.update(reachable[0].features)
        for probe in reachable[1:]:
            common_features.intersection_update(probe.features | extra_verified_features)
    warnings = tuple(
        f"{probe.bucket}:{warning}" for probe in probes for warning in probe.warnings
    )
    return (
        StoragePreflight(
            connected=bool(probes) and not blockers,
            capabilities=StorageCapabilities(features=frozenset(common_features)),
            identity_summary=f"{profile.provider_type.value}:{profile.provider_id}",
            warnings=warnings,
            blockers=blockers,
        ),
        probes,
    )


def create_boto3_s3_client(
    profile: StorageConnectionProfile,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    session_token: str | None = None,
):
    """Lazy boto3 factory supporting AWS credential chain or resolved S3 credentials."""
    try:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
    except ImportError as error:
        raise S3ProviderError("Install the optional S3 provider dependencies") from error

    style = None if profile.addressing_style == "auto" else profile.addressing_style
    config_kwargs: dict[str, Any] = {}
    if style:
        config_kwargs["s3"] = {"addressing_style": style}
    config = botocore_config.Config(**config_kwargs)
    kwargs: dict[str, Any] = {"config": config}
    if profile.endpoint:
        kwargs["endpoint_url"] = profile.endpoint
    if profile.region:
        kwargs["region_name"] = profile.region
    if access_key_id is not None:
        kwargs["aws_access_key_id"] = access_key_id
    if secret_access_key is not None:
        kwargs["aws_secret_access_key"] = secret_access_key
    if session_token is not None:
        kwargs["aws_session_token"] = session_token
    return boto3.client("s3", **kwargs)


def default_provider_features(provider_type: ProviderType) -> frozenset[StorageFeature]:
    """Return only protocol-level features safe to assume before endpoint probing.

    Provider marketing claims are deliberately excluded. Range/multipart are verified
    by integration contract tests before production enablement.
    """
    if provider_type == ProviderType.LOCAL:
        return frozenset({StorageFeature.RANGE_GET})
    return frozenset()
