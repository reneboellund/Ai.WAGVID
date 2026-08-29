import pytest

from wagvid_app.object_provider import (
    GovernanceRequirement,
    ObjectLocation,
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
    evaluate_governance,
)


def test_storage_profile_keeps_secret_value_out_of_configuration():
    profile = StorageConnectionProfile(
        provider_id="primary",
        provider_type=ProviderType.ONTAP_S3,
        endpoint="https://s3.example.internal",
        credential_ref="secret://storage/ontap-primary",
        ca_bundle_ref="secret://pki/internal-ca",
    )
    assert profile.credential_ref.startswith("secret://")
    with pytest.raises(ValueError, match="secret storage"):
        StorageConnectionProfile(
            provider_id="bad",
            provider_type=ProviderType.AWS_S3,
            credential_ref="password=hunter2",
        )


def test_object_location_rejects_traversal_keys():
    ObjectLocation(provider_id="p", bucket="originals", key="org/media.mp4")
    with pytest.raises(ValueError, match="Unsafe object key"):
        ObjectLocation(provider_id="p", bucket="originals", key="org/../secret")


def test_governance_is_capability_driven_not_provider_name_driven():
    profile = StorageConnectionProfile(
        provider_id="vast-primary",
        provider_type=ProviderType.VAST_S3,
        endpoint="https://vast.example.internal",
    )
    preflight = StoragePreflight(
        connected=True,
        capabilities=StorageCapabilities(
            features=frozenset({StorageFeature.RANGE_GET, StorageFeature.MULTIPART})
        ),
    )
    blockers = evaluate_governance(
        profile,
        preflight,
        GovernanceRequirement(
            required_features=frozenset(
                {StorageFeature.RANGE_GET, StorageFeature.MULTIPART, StorageFeature.OBJECT_LOCK}
            )
        ),
    )
    assert blockers == ("missing-capability:object-lock",)


def test_immutable_originals_requires_explicit_object_lock_not_versioning():
    profile = StorageConnectionProfile(
        provider_id="provider",
        provider_type=ProviderType.GENERIC_S3,
        endpoint="https://storage.example",
    )
    versioned_only = evaluate_governance(
        profile,
        StoragePreflight(
            True,
            StorageCapabilities(features=frozenset({StorageFeature.VERSIONING})),
        ),
        GovernanceRequirement(require_immutable_originals=True),
    )
    assert "immutable-originals-unavailable" in versioned_only
    locked = evaluate_governance(
        profile,
        StoragePreflight(
            True,
            StorageCapabilities(features=frozenset({StorageFeature.OBJECT_LOCK})),
        ),
        GovernanceRequirement(require_immutable_originals=True),
    )
    assert locked == ()


def test_preflight_connection_and_tls_fail_closed():
    profile = StorageConnectionProfile(
        provider_id="lab",
        provider_type=ProviderType.GENERIC_S3,
        endpoint="http://lab.invalid",
        tls_required=False,
    )
    blockers = evaluate_governance(
        profile,
        StoragePreflight(False, StorageCapabilities()),
        GovernanceRequirement(require_tls=True),
    )
    assert "provider-unreachable" in blockers
    assert "tls-required" in blockers
