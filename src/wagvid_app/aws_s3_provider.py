"""Native Amazon S3 adapter behind the common object-storage contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .object_provider import (
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)
from .s3_provider import S3DataClient, S3ObjectStorageProvider, S3TransferTuning


AWS_REFERENCE_FEATURES = frozenset(
    {
        StorageFeature.RANGE_GET,
        StorageFeature.MULTIPART,
        StorageFeature.PRESIGNED_GET,
        StorageFeature.PRESIGNED_PUT,
    }
)


def _aws_region(value: Any) -> str:
    if value in (None, ""):
        return "us-east-1"
    if value == "EU":
        return "eu-west-1"
    return str(value)


def _acl_public(value: dict[str, Any]) -> bool:
    for grant in value.get("Grants", []):
        uri = str((grant.get("Grantee") or {}).get("URI") or "")
        if uri.endswith(("/AllUsers", "/AuthenticatedUsers")):
            return True
    return False


@dataclass(frozen=True)
class AwsProvisionAction:
    action: str
    bucket: str
    details: dict[str, Any]
    mutating: bool = True


def plan_aws_bucket_provisioning(
    *,
    desired_buckets: Iterable[str],
    existing_buckets: Iterable[str],
    region: str,
    enable_versioning: bool,
    object_lock_buckets: frozenset[str] = frozenset(),
) -> tuple[AwsProvisionAction, ...]:
    """Pure dry-run planner. Execution belongs to an explicit approval-gated action."""
    existing = set(existing_buckets)
    actions: list[AwsProvisionAction] = []
    for bucket in sorted(set(desired_buckets)):
        if bucket not in existing:
            actions.append(
                AwsProvisionAction(
                    "create-private-bucket",
                    bucket,
                    {"region": region, "object_lock": bucket in object_lock_buckets},
                )
            )
        if enable_versioning:
            actions.append(AwsProvisionAction("ensure-versioning", bucket, {"enabled": True}))
        actions.append(
            AwsProvisionAction(
                "ensure-public-access-block",
                bucket,
                {"all_four_controls": True},
            )
        )
    return tuple(actions)


class AwsS3ObjectStorageProvider(S3ObjectStorageProvider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        account_id: str | None = None,
        transfer_tuning: S3TransferTuning | None = None,
        additional_verified_features: frozenset[StorageFeature] = frozenset(),
    ) -> None:
        if profile.provider_type != ProviderType.AWS_S3:
            raise ValueError("AwsS3ObjectStorageProvider requires provider_type=aws-s3")
        if not profile.region:
            raise ValueError("AWS S3 requires an explicit region")
        self.account_id = account_id
        super().__init__(
            profile,
            client,
            buckets=buckets,
            verified_features=AWS_REFERENCE_FEATURES | additional_verified_features,
            transfer_tuning=transfer_tuning,
        )

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        warnings = list(base.warnings)
        blockers = list(base.blockers)
        features = set(base.capabilities.features)

        for bucket in self.buckets:
            location_call = getattr(self.client, "get_bucket_location", None)
            if location_call is not None:
                try:
                    actual_region = _aws_region(
                        location_call(Bucket=bucket).get("LocationConstraint")
                    )
                    if actual_region != self.profile.region:
                        blockers.append(
                            f"wrong-region:{bucket}:expected={self.profile.region}:actual={actual_region}"
                        )
                except Exception as error:  # noqa: BLE001
                    warnings.append(f"{bucket}:region-unverified:{type(error).__name__}")

            public = False
            acl_call = getattr(self.client, "get_bucket_acl", None)
            if acl_call is not None:
                try:
                    public = _acl_public(acl_call(Bucket=bucket))
                except Exception as error:  # noqa: BLE001
                    warnings.append(f"{bucket}:acl-unverified:{type(error).__name__}")
            policy_status_call = getattr(self.client, "get_bucket_policy_status", None)
            if policy_status_call is not None:
                try:
                    public = public or bool(
                        (policy_status_call(Bucket=bucket).get("PolicyStatus") or {}).get("IsPublic")
                    )
                except Exception as error:  # noqa: BLE001
                    warnings.append(f"{bucket}:policy-public-status-unverified:{type(error).__name__}")
            if public:
                blockers.append(f"public-bucket-rejected:{bucket}")

        identity = "aws-s3"
        if self.account_id:
            identity = f"aws-s3:account-…{self.account_id[-4:]}"
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=frozenset(features),
                notes=base.capabilities.notes,
                max_object_size_bytes=base.capabilities.max_object_size_bytes,
            ),
            identity_summary=identity,
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=tuple(dict.fromkeys(blockers)),
        )
