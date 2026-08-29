from ai_wagvid.cloud_compute import (
    CloudComputePolicy,
    CloudGpuOffering,
    CloudProvider,
    choose_cloud_placement,
)
from ai_wagvid.compute_runtime import ComputeBackend, ExecutionRequirement, Precision


def req(**overrides):
    values = {
        "model_bundle": "pose-v1",
        "allowed_backends": frozenset({ComputeBackend.CUDA}),
        "allowed_precisions": frozenset({Precision.FP16}),
        "minimum_vram_mb": 16000,
        "allow_cloud": True,
    }
    values.update(overrides)
    return ExecutionRequirement(**values)


def policy(**overrides):
    values = {
        "enabled_providers": frozenset(
            {CloudProvider.AWS, CloudProvider.AZURE, CloudProvider.GCP}
        ),
        "allowed_regions": {
            CloudProvider.AWS: frozenset({"eu-west-1"}),
            CloudProvider.AZURE: frozenset({"westeurope"}),
            CloudProvider.GCP: frozenset({"europe-west4"}),
        },
        "allowed_sku_prefixes": {
            CloudProvider.AWS: ("g",),
            CloudProvider.AZURE: ("Standard_NC", "Standard_NV"),
            CloudProvider.GCP: ("g2", "a2", "a3"),
        },
        "max_hourly_cost": 3.0,
        "allow_spot": True,
        "max_workers": 2,
    }
    values.update(overrides)
    return CloudComputePolicy(**values)


def offer(provider, region, sku, cost=1.0, **overrides):
    values = {
        "provider": provider,
        "region": region,
        "zone": None,
        "sku": sku,
        "accelerator_model": "fixture",
        "backend": ComputeBackend.CUDA,
        "vram_mb": 24000,
        "precisions": frozenset({Precision.FP32, Precision.FP16}),
        "hourly_cost": cost,
    }
    values.update(overrides)
    return CloudGpuOffering(**values)


def test_cloud_placement_respects_provider_region_and_sku_policy():
    offerings = [
        offer(CloudProvider.AWS, "us-east-1", "g6.xlarge"),
        offer(CloudProvider.AZURE, "westeurope", "Standard_D2", cost=0.5),
        offer(CloudProvider.GCP, "europe-west4", "g2-standard-8", cost=1.1),
    ]
    decision = choose_cloud_placement(offerings, req(), policy())
    assert decision.selected is not None
    assert decision.selected.offering.provider == CloudProvider.GCP
    reasons = {reason for _, reason in decision.rejected}
    assert "region-not-allowed" in reasons
    assert "sku-not-allowed" in reasons


def test_cloud_placement_never_silently_promotes_above_cost_guard():
    expensive = offer(CloudProvider.AWS, "eu-west-1", "g6.48xlarge", cost=9.0)
    decision = choose_cloud_placement([expensive], req(), policy(max_hourly_cost=2.0))
    assert decision.selected is None
    assert decision.rejected[0][1] == "cost-guard"


def test_unknown_cost_is_blocked_when_cost_guard_is_enabled():
    unknown = offer(CloudProvider.AWS, "eu-west-1", "g6.xlarge", cost=None)
    decision = choose_cloud_placement([unknown], req(), policy(max_hourly_cost=2.0))
    assert decision.selected is None
    assert decision.rejected[0][1] == "cost-unknown"


def test_spot_is_only_selected_when_both_policy_and_request_prefer_it():
    candidate = offer(
        CloudProvider.AWS,
        "eu-west-1",
        "g6.xlarge",
        cost=2.5,
        spot_hourly_cost=0.8,
    )
    on_demand = choose_cloud_placement([candidate], req(), policy(), prefer_spot=False)
    assert on_demand.selected is not None
    assert on_demand.selected.use_spot is False
    spot = choose_cloud_placement([candidate], req(), policy(), prefer_spot=True)
    assert spot.selected is not None
    assert spot.selected.use_spot is True
    assert spot.selected.effective_hourly_cost == 0.8


def test_storage_locality_can_be_a_hard_cloud_placement_gate():
    aws = offer(
        CloudProvider.AWS,
        "eu-west-1",
        "g6.xlarge",
        storage_locality=frozenset({"fsx:media"}),
    )
    gcp = offer(
        CloudProvider.GCP,
        "europe-west4",
        "g2-standard-8",
        storage_locality=frozenset({"gcnv:other"}),
    )
    decision = choose_cloud_placement(
        [gcp, aws],
        req(storage_locality="fsx:media", require_storage_locality=True),
        policy(),
    )
    assert decision.selected is not None
    assert decision.selected.offering.provider == CloudProvider.AWS
    assert any(reason == "storage-locality-required" for _, reason in decision.rejected)


def test_quota_and_capacity_are_runtime_blockers():
    no_quota = offer(
        CloudProvider.AWS,
        "eu-west-1",
        "g6.xlarge",
        quota_available=False,
    )
    no_capacity = offer(
        CloudProvider.GCP,
        "europe-west4",
        "g2-standard-8",
        available=False,
    )
    decision = choose_cloud_placement([no_quota, no_capacity], req(), policy())
    assert decision.selected is None
    assert {reason for _, reason in decision.rejected} == {
        "quota-unavailable",
        "capacity-unavailable",
    }
