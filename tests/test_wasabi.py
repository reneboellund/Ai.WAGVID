from datetime import UTC, datetime, timedelta

import pytest

from wagvid_app.wasabi import (
    BucketRole,
    WasabiCostPolicy,
    WasabiLayoutConfig,
    build_setup_plan,
    reconcile_plan,
    route_object,
)


def config(**overrides):
    values = {
        "project_slug": "wagvid", "environment": "test",
        "account_fingerprint": "a1b2c3d4", "region": "eu-central-1",
    }
    values.update(overrides)
    return WasabiLayoutConfig(**values)


def test_default_plan_has_bounded_role_pools_and_private_buckets():
    plan = build_setup_plan(config(), WasabiCostPolicy())
    assert plan.endpoint == "https://s3.eu-central-1.wasabisys.com"
    assert len([item for item in plan.buckets if item.role is BucketRole.ORIGINALS]) == 2
    assert len([item for item in plan.buckets if item.role is BucketRole.METADATA]) == 1
    assert all(item.private for item in plan.buckets)
    assert all(len(item.name) <= 63 for item in plan.buckets)


def test_rendezvous_routing_is_deterministic_and_role_scoped():
    plan = build_setup_plan(config(), WasabiCostPolicy())
    first = route_object(role=BucketRole.ORIGINALS, routing_key="org/video/hash", buckets=plan.buckets)
    second = route_object(role=BucketRole.ORIGINALS, routing_key="org/video/hash", buckets=plan.buckets)
    assert first == second
    assert first.role is BucketRole.ORIGINALS


def test_cost_policy_calculates_billable_until_and_early_delete_exposure():
    policy = WasabiCostPolicy()
    uploaded = datetime(2026, 1, 1, tzinfo=UTC)
    assert policy.billable_until(uploaded) == uploaded + timedelta(days=90)
    exposure = policy.early_delete_exposure_gb_days(
        size_bytes=10_000_000_000, uploaded_at=uploaded,
        delete_at=uploaded + timedelta(days=30),
    )
    assert exposure == pytest.approx(600)
    assert policy.early_delete_exposure_gb_days(
        size_bytes=10_000_000_000, uploaded_at=uploaded,
        delete_at=uploaded + timedelta(days=100),
    ) == 0


def test_paygo_and_rcs_minimums_must_be_explicit():
    with pytest.raises(ValueError, match="90-day"):
        WasabiCostPolicy("pay-go", 30)
    assert WasabiCostPolicy("rcs", 30).minimum_storage_days == 30


def test_reconcile_is_idempotent_and_blocks_region_or_public_conflicts():
    plan = build_setup_plan(config(originals_shards=1, derivatives_shards=1), WasabiCostPolicy())
    empty_actions = reconcile_plan(plan, {})
    assert any(item.action == "create-private-bucket" for item in empty_actions)
    discovered = {
        bucket.name: {"region": bucket.region, "public": False, "versioning": "Enabled"}
        for bucket in plan.buckets
    }
    assert reconcile_plan(plan, discovered) == ()
    discovered[plan.buckets[0].name]["region"] = "eu-west-1"
    discovered[plan.buckets[1].name]["public"] = True
    actions = reconcile_plan(plan, discovered)
    assert {item.action for item in actions} >= {"block-region-conflict", "block-public-bucket"}
    assert all(item.destructive for item in actions)
