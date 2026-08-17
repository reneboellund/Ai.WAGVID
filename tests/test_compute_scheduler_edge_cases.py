from ai_wagvid.cloud_compute import (
    CloudComputePolicy,
    CloudGpuOffering,
    CloudProvider,
    choose_cloud_placement,
)
from ai_wagvid.compute_runtime import (
    AcceleratorDevice,
    ComputeBackend,
    ExecutionRequirement,
    Precision,
    WorkerCapability,
    rank_candidates,
)


def test_cpu_fallback_is_not_rejected_by_gpu_vram_floor():
    cpu = AcceleratorDevice(
        device_id="cpu:0",
        backend=ComputeBackend.CPU,
        vendor="generic",
        model="CPU",
        precisions=frozenset({Precision.FP32}),
    )
    worker = WorkerCapability(
        worker_id="cpu-worker",
        provider="local",
        location="local",
        devices=(cpu,),
        model_bundles=frozenset({"pose-v1"}),
    )
    requirement = ExecutionRequirement(
        model_bundle="pose-v1",
        allowed_backends=frozenset({ComputeBackend.CUDA}),
        allowed_precisions=frozenset({Precision.FP32}),
        minimum_vram_mb=16000,
        allow_cpu_fallback=True,
    )
    decision = rank_candidates([worker], requirement)
    assert decision.runnable is True
    assert decision.selected.device.device_id == "cpu:0"


def test_cloud_placement_honors_explicit_provider_priority():
    offerings = [
        CloudGpuOffering(
            provider=CloudProvider.AWS,
            region="eu-west-1",
            zone=None,
            sku="g6.xlarge",
            accelerator_model="L4",
            backend=ComputeBackend.CUDA,
            vram_mb=24000,
            precisions=frozenset({Precision.FP16}),
            hourly_cost=1.0,
        ),
        CloudGpuOffering(
            provider=CloudProvider.GCP,
            region="europe-west4",
            zone=None,
            sku="g2-standard-8",
            accelerator_model="L4",
            backend=ComputeBackend.CUDA,
            vram_mb=24000,
            precisions=frozenset({Precision.FP16}),
            hourly_cost=1.0,
        ),
    ]
    policy = CloudComputePolicy(
        enabled_providers=frozenset({CloudProvider.AWS, CloudProvider.GCP}),
        allowed_regions={
            CloudProvider.AWS: frozenset({"eu-west-1"}),
            CloudProvider.GCP: frozenset({"europe-west4"}),
        },
        allowed_sku_prefixes={
            CloudProvider.AWS: ("g6",),
            CloudProvider.GCP: ("g2",),
        },
        max_hourly_cost=2.0,
    )
    requirement = ExecutionRequirement(
        model_bundle="pose-v1",
        allowed_backends=frozenset({ComputeBackend.CUDA}),
        allowed_precisions=frozenset({Precision.FP16}),
        minimum_vram_mb=8000,
        preferred_providers=("gcp", "aws"),
    )
    decision = choose_cloud_placement(offerings, requirement, policy)
    assert decision.selected is not None
    assert decision.selected.offering.provider == CloudProvider.GCP
