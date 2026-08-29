"""NetApp ONTAP S3 adapter using S3 for data and optional ONTAP metadata for diagnostics."""

from __future__ import annotations

from typing import Iterable

from .object_provider import (
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)
from .ontap_management import OntapCapabilities, OntapFeature
from .s3_provider import S3DataClient, S3ObjectStorageProvider, S3TransferTuning
from .s3_validation import S3ContractValidation


ONTAP_CORE_DATA_FEATURES = frozenset({StorageFeature.RANGE_GET, StorageFeature.MULTIPART})


class OntapS3ObjectStorageProvider(S3ObjectStorageProvider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        ontap_capabilities: OntapCapabilities | None = None,
        platform_summary: str | None = None,
        validations: Iterable[S3ContractValidation] = (),
        transfer_tuning: S3TransferTuning | None = None,
    ) -> None:
        if profile.provider_type != ProviderType.ONTAP_S3:
            raise ValueError("OntapS3ObjectStorageProvider requires provider_type=ontap-s3")
        if not profile.endpoint or not profile.endpoint.lower().startswith("https://"):
            raise ValueError("ONTAP S3 production endpoint must use HTTPS")
        self.ontap_capabilities = ontap_capabilities
        self.platform_summary = platform_summary
        validation_tuple = tuple(validations)
        for item in validation_tuple:
            if item.provider_id != profile.provider_id:
                raise ValueError("ONTAP validation belongs to another provider")
        validated_features: set[StorageFeature] = set()
        bucket_tuple = tuple(sorted(set(buckets)))
        if validation_tuple and bucket_tuple:
            by_bucket = {item.bucket: item for item in validation_tuple}
            if all(bucket in by_bucket for bucket in bucket_tuple):
                validated_features = set(by_bucket[bucket_tuple[0]].verified_features)
                for bucket in bucket_tuple[1:]:
                    validated_features.intersection_update(by_bucket[bucket].verified_features)
        super().__init__(
            profile,
            client,
            buckets=bucket_tuple,
            verified_features=ONTAP_CORE_DATA_FEATURES | frozenset(validated_features),
            transfer_tuning=transfer_tuning,
        )

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        blockers = list(base.blockers)
        warnings = list(base.warnings)
        notes = list(base.capabilities.notes)
        features = set(base.capabilities.features)

        if self.ontap_capabilities is not None:
            caps = self.ontap_capabilities
            notes.append(f"ONTAP {caps.version}")
            if not caps.supports(OntapFeature.NATIVE_S3):
                blockers.append("native-ontap-s3-unavailable")
                features.clear()
            if caps.s3_nas:
                warnings.append("s3-nas-mode:advanced-native-s3-governance-disabled")
                features.difference_update(
                    {
                        StorageFeature.VERSIONING,
                        StorageFeature.OBJECT_LOCK,
                        StorageFeature.LIFECYCLE,
                        StorageFeature.BUCKET_POLICY,
                    }
                )
            if not caps.supports(OntapFeature.OBJECT_VERSIONING):
                features.discard(StorageFeature.VERSIONING)
                warnings.append("ontap-release-does-not-support-object-versioning")
            if not caps.supports(OntapFeature.OBJECT_LOCK):
                features.discard(StorageFeature.OBJECT_LOCK)
                warnings.append("ontap-release-does-not-support-object-lock")
            if not caps.supports(OntapFeature.LIFECYCLE):
                features.discard(StorageFeature.LIFECYCLE)
                warnings.append("ontap-release-does-not-support-s3-lifecycle")
            if not caps.supports(OntapFeature.BUCKET_POLICY):
                features.discard(StorageFeature.BUCKET_POLICY)
                warnings.append("ontap-release-does-not-support-bucket-policy")
        else:
            warnings.append("ontap-version-platform-unverified:data-plane-probes-authoritative")

        identity = f"ontap-s3:{self.profile.provider_id}"
        if self.platform_summary:
            identity += f":{self.platform_summary}"
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=frozenset(features),
                notes=tuple(dict.fromkeys(notes)),
                max_object_size_bytes=base.capabilities.max_object_size_bytes,
            ),
            identity_summary=identity,
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=tuple(dict.fromkeys(blockers)),
        )
