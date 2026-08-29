from ai_wagvid.compute_runtime import (
    AcceleratorDevice,
    ComputeBackend,
    ExecutionRequirement,
    Precision,
    WorkerCapability,
    rank_candidates,
)


def gpu(
    device_id: str,
    *,
    backend: ComputeBackend = ComputeBackend.CUDA,
    total_vram_mb: int = 24000,
    free_vram_mb: int = 20000,
    precisions=frozenset({Precision.FP32, Precision.FP16}),
    capabilities=frozenset({"tensor-inference"}),
) -> AcceleratorDevice:
    return AcceleratorDevice(
        device_id=device_id,
        backend=backend,
        vendor="NVIDIA" if backend == ComputeBackend.CUDA else "AMD",
        model="fixture-gpu",
        total_vram_mb=total_vram_mb,
        free_vram_mb=free_vram_mb,
        precisions=precisions,
        capabilities=capabilities,
    )


def requirement(**overrides) -> ExecutionRequirement:
    values = {
        "model_bundle": "pose-v1",
        "allowed_backends": frozenset({ComputeBackend.CUDA, ComputeBackend.ROCM}),
        "allowed_precisions": frozenset({Precision.FP16}),
        "minimum_vram_mb": 8000,
        "preferred_backends": (ComputeBackend.CUDA, ComputeBackend.ROCM),
        "preferred_providers": ("local", "aws", "azure", "gcp"),
        "allow_cloud": True,
    }
    values.update(overrides)
    return ExecutionRequirement(**values)


def test_scheduler_prefers_capable_local_gpu_before_cloud_spillover():
    workers = [
        WorkerCapability(
            worker_id="aws-1",
            provider="aws",
            location="eu-west-1",
            devices=(gpu("aws-l4"),),
            model_bundles=frozenset({"pose-v1"}),
            hourly_cost=1.2,
        ),
        WorkerCapability(
            worker_id="local-1",
            provider="local",
            location="nivaa",
            devices=(gpu("local-rtx"),),
            model_bundles=frozenset({"pose-v1"}),
        ),
    ]
    decision = rank_candidates(workers, requirement())
    assert decision.selected is not None
    assert decision.selected.worker.worker_id == "local-1"


def test_scheduler_rejects_insufficient_vram_and_missing_model():
    workers = [
        WorkerCapability(
            worker_id="small",
            provider="local",
            location="local",
            devices=(gpu("small-gpu", total_vram_mb=6000, free_vram_mb=5000),),
            model_bundles=frozenset({"pose-v1"}),
        ),
        WorkerCapability(
            worker_id="wrong-model",
            provider="local",
            location="local",
            devices=(gpu("big-gpu"),),
            model_bundles=frozenset({"other"}),
        ),
    ]
    decision = rank_candidates(workers, requirement())
    assert decision.runnable is False
    reasons = {item[2] for item in decision.rejected}
    assert "insufficient-vram" in reasons
    assert "model-bundle-unavailable" in reasons


def test_scheduler_enforces_cloud_cost_guard_and_provider_disable():
    cloud = WorkerCapability(
        worker_id="cloud",
        provider="aws",
        location="eu-west-1",
        devices=(gpu("cloud-gpu"),),
        model_bundles=frozenset({"pose-v1"}),
        hourly_cost=8.0,
    )
    expensive = rank_candidates([cloud], requirement(max_hourly_cost=2.0))
    assert expensive.runnable is False
    assert expensive.rejected[0][2] == "cost-guard"
    disabled = rank_candidates([cloud], requirement(allow_cloud=False))
    assert disabled.runnable is False
    assert disabled.rejected[0][2] == "cloud-disabled"


def test_scheduler_can_require_storage_locality():
    near = WorkerCapability(
        worker_id="azure-near",
        provider="azure",
        location="westeurope",
        devices=(gpu("a10"),),
        model_bundles=frozenset({"pose-v1"}),
        storage_locality=frozenset({"anf:media-prod"}),
    )
    far = WorkerCapability(
        worker_id="local-far",
        provider="local",
        location="local",
        devices=(gpu("rtx"),),
        model_bundles=frozenset({"pose-v1"}),
    )
    decision = rank_candidates(
        [far, near],
        requirement(storage_locality="anf:media-prod", require_storage_locality=True),
    )
    assert decision.selected is not None
    assert decision.selected.worker.worker_id == "azure-near"
    assert ("local-far", "rtx", "storage-locality-required") in decision.rejected


def test_cpu_fallback_is_explicit():
    cpu = AcceleratorDevice(
        device_id="cpu0",
        backend=ComputeBackend.CPU,
        vendor="generic",
        model="cpu",
        precisions=frozenset({Precision.FP32}),
    )
    worker = WorkerCapability(
        worker_id="cpu-worker",
        provider="local",
        location="local",
        devices=(cpu,),
        model_bundles=frozenset({"pose-v1"}),
    )
    denied = rank_candidates(
        [worker],
        requirement(
            allowed_backends=frozenset({ComputeBackend.CUDA}),
            allowed_precisions=frozenset({Precision.FP32}),
            minimum_vram_mb=0,
            allow_cpu_fallback=False,
        ),
    )
    assert denied.runnable is False
    allowed = rank_candidates(
        [worker],
        requirement(
            allowed_backends=frozenset({ComputeBackend.CUDA}),
            allowed_precisions=frozenset({Precision.FP32}),
            minimum_vram_mb=0,
            allow_cpu_fallback=True,
        ),
    )
    assert allowed.runnable is True


def test_required_capabilities_fail_closed():
    worker = WorkerCapability(
        worker_id="gpu-worker",
        provider="local",
        location="local",
        devices=(gpu("gpu0", capabilities=frozenset()),),
        model_bundles=frozenset({"pose-v1"}),
    )
    decision = rank_candidates(
        [worker], requirement(required_capabilities=frozenset({"tensor-inference"}))
    )
    assert decision.runnable is False
    assert decision.rejected[0][2] == "capability-missing"
