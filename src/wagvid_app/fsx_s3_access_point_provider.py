"""AWS FSx for ONTAP S3 Access Point object adapter.

FSx S3 Access Points are file-backed object access, not AWS S3 buckets and not native
ONTAP S3 buckets. They deliberately use GENERIC_S3 in the common enum until a later
schema migration adds a dedicated persisted provider type; identity/notes remain explicit.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import BinaryIO

from .object_provider import (
    ObjectLocation,
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)
from .s3_provider import S3DataClient, S3ObjectStorageProvider, S3TransferTuning
from .storage import StoredObject

FSX_ACCESS_POINT_MAX_OBJECT_SIZE = 50 * 1024**3
FSX_ACCESS_POINT_SAFE_FEATURES = frozenset({StorageFeature.RANGE_GET})
FSX_FORBIDDEN_GOVERNANCE = frozenset(
    {
        StorageFeature.PRESIGNED_GET,
        StorageFeature.PRESIGNED_PUT,
        StorageFeature.VERSIONING,
        StorageFeature.OBJECT_LOCK,
        StorageFeature.LEGAL_HOLD,
        StorageFeature.LIFECYCLE,
        StorageFeature.BUCKET_POLICY,
        StorageFeature.PUBLIC_ACCESS_BLOCK,
        StorageFeature.BUCKET_PROVISIONING,
    }
)


class FsxOntapS3AccessPointProvider(S3ObjectStorageProvider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        access_point_aliases: Iterable[str],
        transfer_tuning: S3TransferTuning | None = None,
        additional_validated_features: frozenset[StorageFeature] = frozenset(),
    ) -> None:
        if profile.provider_type != ProviderType.GENERIC_S3:
            raise ValueError("FSx ONTAP S3 Access Point currently uses provider_type=generic-s3")
        if not profile.region:
            raise ValueError("FSx ONTAP S3 Access Point requires an explicit AWS region")
        forbidden = additional_validated_features.intersection(FSX_FORBIDDEN_GOVERNANCE)
        if forbidden:
            values = ",".join(sorted(item.value for item in forbidden))
            raise ValueError(f"FSx S3 Access Point cannot advertise unsupported features: {values}")
        super().__init__(
            profile,
            client,
            buckets=access_point_aliases,
            verified_features=FSX_ACCESS_POINT_SAFE_FEATURES | additional_validated_features,
            transfer_tuning=transfer_tuning,
        )

    def put_verified(
        self,
        location: ObjectLocation,
        source: BinaryIO,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredObject:
        if expected_size > FSX_ACCESS_POINT_MAX_OBJECT_SIZE:
            raise ValueError(
                f"FSx ONTAP S3 Access Point object exceeds {FSX_ACCESS_POINT_MAX_OBJECT_SIZE} bytes"
            )
        return super().put_verified(
            location,
            source,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )

    def create_multipart(self, location: ObjectLocation, *, expected_sha256: str):
        if StorageFeature.MULTIPART not in self.verified_features:
            raise ValueError("Multipart is not validated for this FSx S3 Access Point profile")
        return super().create_multipart(location, expected_sha256=expected_sha256)

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        features = set(base.capabilities.features)
        features.difference_update(FSX_FORBIDDEN_GOVERNANCE)
        notes = list(base.capabilities.notes)
        notes.extend(
            (
                "fsx-ontap-s3-access-point-provider-kind",
                "fsx-ontap-s3-access-point-is-not-aws-s3-bucket",
                "backing-namespace-is-file-storage",
                "governance-must-use-file/protection-controls-not-s3-versioning-or-object-lock",
            )
        )
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=frozenset(features),
                notes=tuple(dict.fromkeys(notes)),
                max_object_size_bytes=FSX_ACCESS_POINT_MAX_OBJECT_SIZE,
            ),
            identity_summary=f"fsx-ontap-s3-access-point:{self.provider_id}",
            warnings=base.warnings,
            blockers=base.blockers,
        )
