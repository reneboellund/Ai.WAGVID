"""VAST Data S3 adapter with capability-validated AWS-subset semantics."""

from __future__ import annotations

from typing import Iterable, Mapping

from .object_provider import ProviderType, StorageCapabilities, StorageConnectionProfile, StoragePreflight
from .s3_provider import S3DataClient, S3TransferTuning
from .s3_validation import S3ContractValidation
from .validated_s3_provider import ContractValidatedS3Provider


class VastS3ObjectStorageProvider(ContractValidatedS3Provider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        validations: Iterable[S3ContractValidation] = (),
        transfer_tuning: S3TransferTuning | None = None,
        vms_diagnostics: Mapping[str, str | int | float] | None = None,
        multiprotocol_view: bool = False,
    ) -> None:
        if profile.provider_type != ProviderType.VAST_S3:
            raise ValueError("VastS3ObjectStorageProvider requires provider_type=vast-s3")
        if not profile.endpoint or not profile.endpoint.lower().startswith("https://"):
            raise ValueError("VAST S3 production endpoint must use HTTPS")
        self.vms_diagnostics = dict(vms_diagnostics or {})
        self.multiprotocol_view = multiprotocol_view
        super().__init__(
            profile,
            client,
            buckets=buckets,
            validations=validations,
            transfer_tuning=transfer_tuning,
        )

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        warnings = list(base.warnings)
        notes = list(base.capabilities.notes)
        if self.multiprotocol_view:
            warnings.append(
                "multiprotocol-view:do-not-assume-posix-path-equivalence-or-concurrent-cross-protocol-writes"
            )
        if self.vms_diagnostics:
            notes.append("read-only-vms-diagnostics-configured")
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=base.capabilities.features,
                notes=tuple(dict.fromkeys(notes)),
                max_object_size_bytes=base.capabilities.max_object_size_bytes,
            ),
            identity_summary=f"vast-s3:{self.profile.provider_id}",
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=base.blockers,
        )
