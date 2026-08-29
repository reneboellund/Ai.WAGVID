import pytest

from wagvid_app.ontap_management import (
    OntapBucketState,
    OntapCapabilities,
    OntapDesiredBucket,
    OntapDesiredLayout,
    OntapDiscovery,
    OntapFeature,
    OntapVersion,
    plan_ontap_setup,
    plan_snapmirror_s3,
)


def discovery(version="9.16.1", **overrides):
    values = {
        "version": OntapVersion.parse(version),
        "svm_uuid": "svm-1",
        "svm_name": "wagvid-svm",
        "s3_service_exists": True,
        "user_names": frozenset({"ai-wagvid"}),
        "group_names": frozenset({"ai-wagvid"}),
        "buckets": {},
    }
    values.update(overrides)
    return OntapDiscovery(**values)


def test_ontap_feature_matrix_tracks_documented_release_gates():
    assert OntapFeature.NATIVE_S3 in OntapCapabilities(OntapVersion.parse("9.8")).features
    assert OntapFeature.SNAPMIRROR_S3 in OntapCapabilities(
        OntapVersion.parse("9.10.1")
    ).features
    assert OntapFeature.OBJECT_VERSIONING in OntapCapabilities(
        OntapVersion.parse("9.11.1")
    ).features
    assert OntapFeature.LIFECYCLE in OntapCapabilities(OntapVersion.parse("9.13.1")).features
    assert OntapFeature.OBJECT_LOCK in OntapCapabilities(
        OntapVersion.parse("9.14.1")
    ).features
    assert OntapFeature.S3_SNAPSHOTS in OntapCapabilities(
        OntapVersion.parse("9.16.1")
    ).features


def test_s3_nas_does_not_inherit_native_s3_protection_features():
    features = OntapCapabilities(
        OntapVersion.parse("9.19.1"), native_s3=True, s3_nas=True
    ).features
    assert features == frozenset({OntapFeature.NATIVE_S3})


def test_setup_plan_creates_user_group_and_bucket_with_exact_retention_payload():
    state = discovery(
        s3_service_exists=False,
        user_names=frozenset(),
        group_names=frozenset(),
    )
    desired = OntapDesiredLayout(
        s3_user_name="ai-wagvid",
        s3_group_name="ai-wagvid",
        buckets=(
            OntapDesiredBucket(
                role="originals",
                name="wagvid-originals",
                versioning=True,
                retention_mode="governance",
                retention_days=90,
                snapshot_policy="daily-s3",
            ),
        ),
        audit_required=True,
    )
    plan = plan_ontap_setup(state, desired)
    assert plan.applicable is True
    actions = {action.action: action for action in plan.actions}
    assert "create-s3-service" in actions
    assert "create-s3-user" in actions
    assert "create-s3-group" in actions
    bucket = actions["create-bucket"]
    assert bucket.payload["versioning_state"] == "enabled"
    assert bucket.payload["retention"] == {
        "mode": "governance",
        "default_period": "P90D",
    }
    assert bucket.payload["snapshot_policy"] == {"name": "daily-s3"}
    assert "ensure-s3-audit" in actions


def test_old_ontap_blocks_requested_newer_protection_without_silent_downgrade():
    desired = OntapDesiredLayout(
        s3_user_name="ai-wagvid",
        s3_group_name="ai-wagvid",
        buckets=(
            OntapDesiredBucket(
                role="originals",
                name="wagvid-originals",
                versioning=True,
                retention_mode="compliance",
                retention_days=365,
                snapshot_policy="daily",
            ),
        ),
    )
    plan = plan_ontap_setup(discovery("9.12.1"), desired)
    assert plan.applicable is False
    assert any("object-lock-requires" in blocker for blocker in plan.blockers)
    assert any("s3-snapshots-require" in blocker for blocker in plan.blockers)


def test_existing_unlocked_bucket_is_not_mutated_into_object_lock():
    state = discovery(
        buckets={
            "wagvid-originals": OntapBucketState(
                "wagvid-originals", uuid="bucket-1", retention_mode="no_lock"
            )
        }
    )
    desired = OntapDesiredLayout(
        s3_user_name="ai-wagvid",
        s3_group_name="ai-wagvid",
        buckets=(
            OntapDesiredBucket(
                role="originals",
                name="wagvid-originals",
                retention_mode="governance",
                retention_days=90,
            ),
        ),
    )
    plan = plan_ontap_setup(state, desired)
    assert "wagvid-originals:object-lock-cannot-be-enabled-after-bucket-creation" in plan.blockers


def test_lifecycle_is_reserved_for_transient_data_and_version_gated():
    desired = OntapDesiredLayout(
        s3_user_name="ai-wagvid",
        s3_group_name="ai-wagvid",
        buckets=(
            OntapDesiredBucket(
                role="derivatives",
                name="wagvid-derivatives",
                lifecycle_expire_days=30,
            ),
        ),
    )
    old = plan_ontap_setup(discovery("9.12.1"), desired)
    assert any("lifecycle-requires" in blocker for blocker in old.blockers)
    current = plan_ontap_setup(discovery("9.16.1"), desired)
    lifecycle = [action for action in current.actions if action.action == "ensure-lifecycle-rule"]
    assert lifecycle[0].payload["expiration"]["object_age_days"] == 30


def test_snapmirror_s3_is_planned_only_when_supported_and_not_metrocluster():
    source = discovery(
        "9.16.1",
        buckets={"originals": OntapBucketState("originals", uuid="bucket-1")},
    )
    plan = plan_snapmirror_s3(
        source,
        source_bucket="originals",
        destination="dr-svm:originals-dr",
    )
    assert plan.applicable is True
    assert plan.actions[0].endpoint == "/api/snapmirror/relationships"

    metro = discovery(
        "9.16.1",
        metrocluster=True,
        buckets={"originals": OntapBucketState("originals", uuid="bucket-1")},
    )
    blocked = plan_snapmirror_s3(
        metro,
        source_bucket="originals",
        destination="dr-svm:originals-dr",
    )
    assert blocked.blockers == ("snapmirror-s3-unavailable",)


def test_desired_object_lock_requires_explicit_retention_period():
    with pytest.raises(ValueError, match="retention_days"):
        OntapDesiredBucket(
            role="originals",
            name="originals",
            retention_mode="governance",
        )
