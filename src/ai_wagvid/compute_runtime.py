"""Provider-neutral accelerator capability and scheduling contracts.

No vendor SDK is imported here. Local NVIDIA/AMD/Intel discovery and cloud provider
adapters translate their observations into these records, keeping model execution and
job scheduling independent of CUDA/ROCm/OpenVINO/AWS/Azure/GCP APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class ComputeBackend(StrEnum):
    CPU = "cpu"
    CUDA = "cuda"
    ROCM = "rocm"
    OPENVINO_GPU = "openvino-gpu"
    CLOUD = "cloud"


class Precision(StrEnum):
    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    INT8 = "int8"


@dataclass(frozen=True)
class AcceleratorDevice:
    device_id: str
    backend: ComputeBackend
    vendor: str
    model: str
    architecture: str | None = None
    device_index: int | None = None
    total_vram_mb: int | None = None
    free_vram_mb: int | None = None
    driver_version: str | None = None
    runtime_version: str | None = None
    precisions: frozenset[Precision] = frozenset({Precision.FP32})
    capabilities: frozenset[str] = frozenset()

    @property
    def is_gpu(self) -> bool:
        return self.backend != ComputeBackend.CPU


@dataclass(frozen=True)
class WorkerCapability:
    worker_id: str
    provider: str
    location: str
    devices: tuple[AcceleratorDevice, ...]
    model_bundles: frozenset[str]
    queue_depth: int = 0
    active_jobs: int = 0
    healthy: bool = True
    ephemeral: bool = False
    hourly_cost: float | None = None
    storage_locality: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ExecutionRequirement:
    model_bundle: str
    allowed_backends: frozenset[ComputeBackend]
    allowed_precisions: frozenset[Precision]
    minimum_vram_mb: int = 0
    preferred_backends: tuple[ComputeBackend, ...] = ()
    preferred_providers: tuple[str, ...] = ()
    storage_locality: str | None = None
    require_storage_locality: bool = False
    allow_cpu_fallback: bool = False
    allow_cloud: bool = True
    max_hourly_cost: float | None = None
    required_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Candidate:
    worker: WorkerCapability
    device: AcceleratorDevice
    score: tuple
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchedulingDecision:
    selected: Candidate | None
    rejected: tuple[tuple[str, str, str], ...] = ()

    @property
    def runnable(self) -> bool:
        return self.selected is not None


def _backend_rank(backend: ComputeBackend, preferred: tuple[ComputeBackend, ...]) -> int:
    try:
        return preferred.index(backend)
    except ValueError:
        return len(preferred) + 1


def _provider_rank(provider: str, preferred: tuple[str, ...]) -> int:
    try:
        return preferred.index(provider)
    except ValueError:
        return len(preferred) + 1


def _compatible(
    worker: WorkerCapability,
    device: AcceleratorDevice,
    requirement: ExecutionRequirement,
) -> tuple[bool, str | None]:
    if not worker.healthy:
        return False, "worker-unhealthy"
    if requirement.model_bundle not in worker.model_bundles:
        return False, "model-bundle-unavailable"
    if device.backend not in requirement.allowed_backends:
        if not (device.backend == ComputeBackend.CPU and requirement.allow_cpu_fallback):
            return False, "backend-not-allowed"
    if worker.provider != "local" and not requirement.allow_cloud:
        return False, "cloud-disabled"
    if requirement.max_hourly_cost is not None and worker.hourly_cost is not None:
        if worker.hourly_cost > requirement.max_hourly_cost:
            return False, "cost-guard"
    if requirement.storage_locality:
        local = requirement.storage_locality in worker.storage_locality
        if requirement.require_storage_locality and not local:
            return False, "storage-locality-required"
    # VRAM is a GPU resource. Explicit CPU fallback remains valid even when the GPU
    # execution contract carries a non-zero VRAM floor.
    if requirement.minimum_vram_mb and device.is_gpu:
        if device.total_vram_mb is None or device.total_vram_mb < requirement.minimum_vram_mb:
            return False, "insufficient-vram"
        if device.free_vram_mb is not None and device.free_vram_mb < requirement.minimum_vram_mb:
            return False, "insufficient-free-vram"
    if not requirement.allowed_precisions.intersection(device.precisions):
        return False, "precision-incompatible"
    if not requirement.required_capabilities.issubset(device.capabilities):
        return False, "capability-missing"
    return True, None


def rank_candidates(
    workers: Iterable[WorkerCapability], requirement: ExecutionRequirement
) -> SchedulingDecision:
    """Return a deterministic best candidate and explicit rejection reasons.

    Ranking prefers configured backend/provider order, matching storage locality,
    lower queue/load and lower known cost. Stable worker/device IDs are final tie-breakers.
    """
    candidates: list[Candidate] = []
    rejected: list[tuple[str, str, str]] = []
    for worker in workers:
        for device in worker.devices:
            compatible, reason = _compatible(worker, device, requirement)
            if not compatible:
                rejected.append((worker.worker_id, device.device_id, reason or "incompatible"))
                continue
            locality_penalty = 0
            if requirement.storage_locality:
                locality_penalty = int(requirement.storage_locality not in worker.storage_locality)
            known_cost = worker.hourly_cost if worker.hourly_cost is not None else float("inf")
            cloud_penalty = int(worker.provider != "local")
            score = (
                _backend_rank(device.backend, requirement.preferred_backends),
                _provider_rank(worker.provider, requirement.preferred_providers),
                locality_penalty,
                cloud_penalty,
                worker.queue_depth,
                worker.active_jobs,
                known_cost,
                worker.worker_id,
                device.device_id,
            )
            candidates.append(Candidate(worker=worker, device=device, score=score))
    candidates.sort(key=lambda item: item.score)
    rejected.sort()
    return SchedulingDecision(
        selected=candidates[0] if candidates else None,
        rejected=tuple(rejected),
    )
