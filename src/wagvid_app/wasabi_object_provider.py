"""Bridge the existing Wasabi setup/control plane to the provider-neutral S3 data plane.

This intentionally does not replace `wasabi.py` or `wasabi_provider.py`. The existing
layout, retention/cost and approval-gated provisioning logic remains authoritative;
this adapter only makes an already-configured Wasabi connection usable through the
same ObjectStorageProvider boundary as AWS S3, ONTAP S3, VAST and Ootbi.
"""

from __future__ import annotations

from collections.abc import Iterable

from .object_provider import (
    ObjectStorageProvider,
    ProviderType,
    StorageConnectionProfile,
    StorageFeature,
)
from .s3_provider import S3DataClient, S3ObjectStorageProvider


WASABI_DATA_PLANE_FEATURES = frozenset(
    {
        StorageFeature.RANGE_GET,
        StorageFeature.MULTIPART,
    }
)


class WasabiObjectStorageProvider(S3ObjectStorageProvider):
    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        additional_verified_features: frozenset[StorageFeature] = frozenset(),
    ) -> None:
        if profile.provider_type != ProviderType.WASABI:
            raise ValueError("WasabiObjectStorageProvider requires provider_type=wasabi")
        super().__init__(
            profile,
            client,
            buckets=buckets,
            verified_features=WASABI_DATA_PLANE_FEATURES | additional_verified_features,
        )


def build_wasabi_object_provider(
    *,
    provider_id: str,
    endpoint: str,
    region: str,
    credential_ref: str,
    client: S3DataClient,
    buckets: Iterable[str],
    ca_bundle_ref: str | None = None,
    addressing_style: str = "auto",
    additional_verified_features: frozenset[StorageFeature] = frozenset(),
) -> ObjectStorageProvider:
    """Build the neutral data-plane adapter from the existing Wasabi connection data."""

    profile = StorageConnectionProfile(
        provider_id=provider_id,
        provider_type=ProviderType.WASABI,
        endpoint=endpoint,
        region=region,
        credential_ref=credential_ref,
        ca_bundle_ref=ca_bundle_ref,
        addressing_style=addressing_style,
        tls_required=True,
    )
    return WasabiObjectStorageProvider(
        profile,
        client,
        buckets=buckets,
        additional_verified_features=additional_verified_features,
    )
