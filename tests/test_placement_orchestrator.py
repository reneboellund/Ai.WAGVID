from datetime import UTC, datetime, timedelta

import pytest

from ai_wagvid.cloud_compute import CloudComputePolicy, CloudGpuOffering, CloudProvider
from ai_wagvid.compute_runtime import (
    AcceleratorDevice,
    ComputeBackend,
    Precision,
    WorkerCapability,
)
from ai_wagvid.placement_orchestrator import (
    AnalysisPlacementRequest,
    PlacementKind,
    create_execution_lease,
    plan_analysis_placement,
)


NOW = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


def local_worker(
    *,
    backend=ComputeBackend.CUDA,
    vram=12_000,
    locality=frozenset({"storage:local"}),
    healthy=True,
):
    device = AcceleratorDevice(
        device_id="gpu-0" if backend != ComputeBackend.CPU else "cpu-0",
        backend=backend,
        vendor="nvidia" if backend == ComputeBackend.CUDA else "generic",
        model="test-device",
        total_vram_mb=None if backend == ComputeBackend.CPU else vram,
        free_vram_mb=None if backend == ComputeBackend.CPU else vram,
        precisions=frozenset({Precision.FP32, Precision.FP16}),
        capabilities=frozenset({"video-decode"}),
    )
    return WorkerCapability(
        worker_id="local-worker",
        provider="local",
        location="on-prem",
        devices=(device,),
        model_bundles=frozenset({"competition@1"}),
        healthy=healthy,
        storage_locality=locality,
    )


def cloud_offering(*, cost=1.25, locality=frozenset({"storage:aws"}), available=True):
    return CloudGpuOffering(
        provider=CloudProvider.AWS,
        region="eu-central-1",
        zone="eu-central-1a",
        sku="g5.xlarge",
        accelerator_model="A10G",
        backend=ComputeBackend.CUDA,
        vram_mb=24_000,
        precisions=frozenset({Precision.FP32, Precision.FP16}),
        capabilities=frozenset({"video-decode"}),
        available=available,
        quota_available=True,
        hourly_cost=cost,
        spot_hourly_cost=0.55,
        storage_locality=locality,
    )


def cloud_policy(max_cost=2.0):
    return CloudComputePolicy(
        enabled_providers=frozenset({CloudProvider.AWS}),
        allowed_regions={CloudProvider.AWS: frozenset({"eu-central-1"})},
        allowed_sku_prefixes={CloudProvider.AWS: ("g5",)},
        max_hourly_cost=max_cost,
        allow_spot=True,
        max_workers=2,
    )


def request(**overrides):
    values = dict(
        job_id="job-1",
        model_bundle="competition@1",
        allowed_backends=frozenset({ComputeBackend.CUDA}),
        allowed_precisions=frozenset({Precision.FP16}),
        minimum_vram_mb=8_000,
        preferred_backends=(ComputeBackend.CUDA,),
        preferred_providers=("local", "aws"),
        required_capabilities=frozenset({"video-decode"}),
        allow_cpu_fallback=False,
        allow_cloud=True,
        max_hourly_cost=2.0,
    )
    values.update(overrides)
    return AnalysisPlacementRequest(**values)


def test_compatible_local_worker_wins_before_cloud_even_when_cloud_is_cheap():
    decision = plan_analysis_placement(
        request(),
        local_workers=[local_worker()],
        cloud_offerings=[cloud_offering(cost=0.01)],
        cloud_policy=cloud_policy(),
    )
    assert decision.runnable
    assert decision.target.kind == PlacementKind.LOCAL_WORKER
    assert decision.target.worker_id == "local-worker"
    assert decision.cloud is None


def test_cloud_spillover_requires_policy_and_preserves_cost_guard():
    no_policy = plan_analysis_placement(
        request(), local_workers=[], cloud_offerings=[cloud_offering()], cloud_policy=None
    )
    assert not no_policy.runnable
    assert no_policy.blockers == ("cloud-policy-required-for-spillover",)

    too_expensive = plan_analysis_placement(
        request(max_hourly_cost=0.25),
        local_workers=[],
        cloud_offerings=[cloud_offering(cost=1.0)],
        cloud_policy=cloud_policy(max_cost=2.0),
    )
    assert not too_expensive.runnable
    assert too_expensive.blockers == ("no-compatible-cloud-offering",)


def test_cloud_spillover_selects_spot_only_when_policy_and_request_allow_it():
    decision = plan_analysis_placement(
        request(prefer_spot=True),
        local_workers=[],
        cloud_offerings=[cloud_offering(cost=1.5)],
        cloud_policy=cloud_policy(),
    )
    assert decision.runnable
    assert decision.target.kind == PlacementKind.CLOUD_OFFERING
    assert decision.target.cloud_placement.use_spot
    assert decision.target.hourly_cost == 0.55
    assert "cloud-spillover-selected" in decision.warnings


def test_required_storage_locality_blocks_remote_local_worker_and_can_spill_to_matching_cloud():
    decision = plan_analysis_placement(
        request(storage_locality="storage:aws", require_storage_locality=True),
        local_workers=[local_worker(locality=frozenset({"storage:local"}))],
        cloud_offerings=[cloud_offering(locality=frozenset({"storage:aws"}))],
        cloud_policy=cloud_policy(),
    )
    assert decision.runnable
    assert decision.target.kind == PlacementKind.CLOUD_OFFERING


def test_cloud_disabled_fails_closed_after_local_rejection():
    decision = plan_analysis_placement(
        request(allow_cloud=False),
        local_workers=[local_worker(healthy=False)],
        cloud_offerings=[cloud_offering()],
        cloud_policy=cloud_policy(),
    )
    assert not decision.runnable
    assert decision.blockers == ("no-compatible-local-worker-and-cloud-disabled",)


def test_local_worker_input_cannot_smuggle_cloud_worker_into_local_phase():
    worker = local_worker()
    cloud_like = WorkerCapability(
        worker_id=worker.worker_id,
        provider="aws",
        location=worker.location,
        devices=worker.devices,
        model_bundles=worker.model_bundles,
    )
    with pytest.raises(ValueError, match="provider='local'"):
        plan_analysis_placement(request(), local_workers=[cloud_like])


def test_execution_lease_is_deterministic_per_job_attempt_and_target():
    decision = plan_analysis_placement(request(), local_workers=[local_worker()])
    first = create_execution_lease(decision, attempt=1, issued_at=NOW)
    second = create_execution_lease(decision, attempt=1, issued_at=NOW + timedelta(seconds=1))
    assert first.lease_id == second.lease_id
    assert first.idempotency_key == second.idempotency_key
    assert first.active_at(NOW + timedelta(minutes=1))
    assert not first.active_at(first.expires_at)

    retry = create_execution_lease(decision, attempt=2, issued_at=NOW)
    assert retry.lease_id != first.lease_id


def test_lease_ttl_is_bounded():
    decision = plan_analysis_placement(request(), local_workers=[local_worker()])
    with pytest.raises(ValueError, match="no more than one hour"):
        create_execution_lease(decision, attempt=1, issued_at=NOW, ttl=timedelta(hours=2))
