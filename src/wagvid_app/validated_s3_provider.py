"""Shared base for S3 providers that require endpoint contract certification."""

from __future__ import annotations

from collections.abc import Iterable

from .object_provider import (
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)
from .s3_provider import S3DataClient, S3ObjectStorageProvider, S3TransferTuning
from .s3_validation import S3ContractValidation


def common_validated_features(
    validations: Iterable[S3ContractValidation], buckets: Iterable[str]
) -> frozenset[StorageFeature]:
    by_bucket = {item.bucket: item for item in validations}
    required = tuple(sorted(set(buckets)))
    if not required or any(bucket not in by_bucket for bucket in required):
        return frozenset()
    common = set(by_bucket[required[0]].verified_features)
    for bucket in required[1:]:
        common.intersection_update(by_bucket[bucket].verified_features)
    return frozenset(common)


class ContractValidatedS3Provider(S3ObjectStorageProvider):
    """S3 data plane that fails health/preflight until every mapped bucket passes core tests."""

    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        validations: Iterable[S3ContractValidation] = (),
        baseline_features: frozenset[StorageFeature] = frozenset(),
        transfer_tuning: S3TransferTuning | None = None,
    ) -> None:
        bucket_tuple = tuple(sorted(set(buckets)))
        validation_tuple = tuple(validations)
        self.validations = {item.bucket: item for item in validation_tuple}
        for item in validation_tuple:
            if item.provider_id != profile.provider_id:
                raise ValueError("S3 validation belongs to another provider")
        super().__init__(
            profile,
            client,
            buckets=bucket_tuple,
            verified_features=baseline_features
            | common_validated_features(validation_tuple, bucket_tuple),
            transfer_tuning=transfer_tuning,
        )

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        blockers = list(base.blockers)
        warnings = list(base.warnings)
        for bucket in self.buckets:
            validation = self.validations.get(bucket)
            if validation is None:
                blockers.append(f"provider-contract-unvalidated:{bucket}")
                continue
            if not validation.core_validated:
                blockers.append(f"provider-contract-incompatible:{bucket}")
            if validation.failed_operations:
                warnings.append(
                    f"{bucket}:optional-or-policy-probe-failures:{len(validation.failed_operations)}"
                )
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=base.capabilities.features,
                notes=base.capabilities.notes,
                max_object_size_bytes=base.capabilities.max_object_size_bytes,
            ),
            identity_summary=base.identity_summary,
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=tuple(dict.fromkeys(blockers)),
        )
