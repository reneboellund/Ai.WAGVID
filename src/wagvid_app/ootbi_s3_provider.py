"""Object First Ootbi conditional S3 adapter.

Ootbi remains existing-bucket only in v1. It is not marked usable until the configured
bucket passes the explicit S3 contract probe; no appliance management API is used.
"""

from __future__ import annotations

from typing import Callable, Iterable

from .object_provider import ProviderType, StorageCapabilities, StorageConnectionProfile, StoragePreflight
from .s3_provider import S3DataClient, S3TransferTuning
from .s3_validation import ProviderSupportState, S3ContractValidation
from .validated_s3_provider import ContractValidatedS3Provider


class RetentionProtectedError(RuntimeError):
    """Deletion was rejected because provider/appliance retention is authoritative."""


class OotbiS3ObjectStorageProvider(ContractValidatedS3Provider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        validations: Iterable[S3ContractValidation] = (),
        transfer_tuning: S3TransferTuning | None = None,
        retention_error_classifier: Callable[[Exception], bool] | None = None,
    ) -> None:
        if profile.provider_type != ProviderType.OOTBI_S3:
            raise ValueError("OotbiS3ObjectStorageProvider requires provider_type=ootbi-s3")
        if not profile.endpoint or not profile.endpoint.lower().startswith("https://"):
            raise ValueError("Ootbi S3 production endpoint must use HTTPS")
        self.retention_error_classifier = retention_error_classifier
        super().__init__(
            profile,
            client,
            buckets=buckets,
            validations=validations,
            transfer_tuning=transfer_tuning,
        )

    @property
    def support_state(self) -> ProviderSupportState:
        if not self.buckets:
            return ProviderSupportState.INCOMPATIBLE
        records = [self.validations.get(bucket) for bucket in self.buckets]
        if any(record is None for record in records):
            return ProviderSupportState.UNVALIDATED
        if any(not record.core_validated for record in records if record is not None):
            return ProviderSupportState.INCOMPATIBLE
        if any(record.failed_operations for record in records if record is not None):
            return ProviderSupportState.LIMITED
        return ProviderSupportState.VALIDATED

    def preflight(self) -> StoragePreflight:
        base = super().preflight()
        warnings = list(base.warnings)
        notes = list(base.capabilities.notes)
        state = self.support_state
        notes.extend(
            (
                f"support-state:{state.value}",
                "existing-bucket-mode-only",
                "no-appliance-management-automation",
                "derivatives-and-temp-should-use-another-provider-when-retention-is-long-lived",
            )
        )
        if state == ProviderSupportState.LIMITED:
            warnings.append("ootbi-core-s3-validated-with-optional-or-policy-limitations")
        return StoragePreflight(
            connected=base.connected,
            capabilities=StorageCapabilities(
                features=base.capabilities.features,
                notes=tuple(dict.fromkeys(notes)),
                max_object_size_bytes=base.capabilities.max_object_size_bytes,
            ),
            identity_summary=f"ootbi-s3:{self.profile.provider_id}:{state.value}",
            warnings=tuple(dict.fromkeys(warnings)),
            blockers=base.blockers,
        )

    def delete(self, location) -> None:
        try:
            super().delete(location)
        except Exception as error:  # noqa: BLE001 - appliance/provider errors are classifier input
            if self.retention_error_classifier and self.retention_error_classifier(error):
                raise RetentionProtectedError(
                    "Ootbi rejected deletion due to appliance-enforced retention"
                ) from error
            raise
