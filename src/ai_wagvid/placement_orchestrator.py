"""Deterministic analysis placement across local accelerators and cloud spillover.

This module is intentionally control-plane only: it never imports CUDA/ROCm/OpenVINO or
cloud SDKs and never provisions a worker. It consumes already-discovered capabilities and
produces a target/lease plan that provider adapters may execute later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from .cloud_compute import (
    CloudComputePolicy,
    CloudGpuOffering,
    CloudPlacement,
    CloudPlacementDecision,
    choose_cloud_placement,
)
from .compute_runtime import (
    ComputeBackend,
    ExecutionRequirement,
    Precision,
    SchedulingDecision,
    WorkerCapability,
    rank_candidates,
)


class PlacementKind(StrEnum):
    LOCAL_WORKER = "local-worker"
    CLOUD_OFFERING = "cloud-offering"


@dataclass(frozen=True)
class AnalysisPlacementRequest:
    job_id: str
    model_bundle: str
    allowed_backends: frozenset[ComputeBackend]
    allowed_precisions: frozenset[Precision]
    minimum_vram_mb: int = 0
    preferred_backends: tuple[ComputeBackend, ...] = ()
    preferred_providers: tuple[str, ...] = ()
    storage_locality: str | None = None
    require_storage_locality: bool = False
    required_capabilities: frozenset[str] = frozenset()
    allow_cpu_fallback: bool = False
    allow_cloud: bool = True
    max_hourly_cost: float | None = None
    prefer_spot: bool = False

    def __post_init__(self) -> None:
        if not self.job_id or not self.model_bundle:
            raise ValueError("job_id and model_bundle are required")
        if self.minimum_vram_mb < 0:
            raise ValueError("minimum_vram_mb cannot be negative")
        if self.max_hourly_cost is not None and self.max_hourly_cost < 0:
            raise ValueError("max_hourly_cost cannot be negative")

    def requirement(self) -> ExecutionRequirement:
        return ExecutionRequirement(
            model_bundle=self.model_bundle,
            allowed_backends=self.allowed_backends,
            allowed_precisions=self.allowed_precisions,
            minimum_vram_mb=self.minimum_vram_mb,
            preferred_backends=self.preferred_backends,
            preferred_providers=self.preferred_providers,
            storage_locality=self.storage_locality,
            require_storage_locality=self.require_storage_locality,
            allow_cpu_fallback=self.allow_cpu_fallback,
            allow_cloud=self.allow_cloud,
            max_hourly_cost=self.max_hourly_cost,
            required_capabilities=self.required_capabilities,
        )


@dataclass(frozen=True)
class PlacementTarget:
    kind: PlacementKind
    identity: str
    backend: ComputeBackend
    provider: str
    location: str
    hourly_cost: float | None
    storage_locality: frozenset[str]
    worker_id: str | None = None
    device_id: str | None = None
    cloud_placement: CloudPlacement | None = None


@dataclass(frozen=True)
class PlacementDecision:
    request: AnalysisPlacementRequest
    target: PlacementTarget | None
    local: SchedulingDecision
    cloud: CloudPlacementDecision | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def runnable(self) -> bool:
        return self.target is not None and not self.blockers


@dataclass(frozen=True)
class ExecutionLease:
    lease_id: str
    job_id: str
    target_identity: str
    attempt: int
    issued_at: datetime
    expires_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        if any(value.tzinfo is None or value.utcoffset() is None for value in (self.issued_at, self.expires_at)):
            raise ValueError("lease timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("lease expiry must follow issue time")

    def active_at(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.issued_at.astimezone(UTC) <= now.astimezone(UTC) < self.expires_at.astimezone(UTC)


def plan_analysis_placement(
    request: AnalysisPlacementRequest,
    *,
    local_workers: Iterable[WorkerCapability],
    cloud_offerings: Iterable[CloudGpuOffering] = (),
    cloud_policy: CloudComputePolicy | None = None,
) -> PlacementDecision:
    requirement = request.requirement()
    local_workers = tuple(local_workers)
    if any(worker.provider != "local" for worker in local_workers):
        raise ValueError("local_workers must contain only provider='local' workers")

    local = rank_candidates(local_workers, requirement)
    if local.selected is not None:
        candidate = local.selected
        return PlacementDecision(
            request=request,
            target=PlacementTarget(
                kind=PlacementKind.LOCAL_WORKER,
                identity=f"local:{candidate.worker.worker_id}:{candidate.device.device_id}",
                backend=candidate.device.backend,
                provider="local",
                location=candidate.worker.location,
                hourly_cost=candidate.worker.hourly_cost,
                storage_locality=candidate.worker.storage_locality,
                worker_id=candidate.worker.worker_id,
                device_id=candidate.device.device_id,
            ),
            local=local,
            cloud=None,
        )

    if not request.allow_cloud:
        return PlacementDecision(
            request=request,
            target=None,
            local=local,
            cloud=None,
            blockers=("no-compatible-local-worker-and-cloud-disabled",),
        )
    if cloud_policy is None:
        return PlacementDecision(
            request=request,
            target=None,
            local=local,
            cloud=None,
            blockers=("cloud-policy-required-for-spillover",),
        )

    cloud = choose_cloud_placement(
        tuple(cloud_offerings), requirement, cloud_policy, prefer_spot=request.prefer_spot
    )
    if cloud.selected is None:
        return PlacementDecision(
            request=request,
            target=None,
            local=local,
            cloud=cloud,
            blockers=("no-compatible-cloud-offering",),
        )

    selected = cloud.selected
    offering = selected.offering
    return PlacementDecision(
        request=request,
        target=PlacementTarget(
            kind=PlacementKind.CLOUD_OFFERING,
            identity=(
                f"cloud:{offering.provider.value}:{offering.region}:"
                f"{offering.zone or '-'}:{offering.sku}"
            ),
            backend=offering.backend,
            provider=offering.provider.value,
            location=f"{offering.region}/{offering.zone or '-'}",
            hourly_cost=selected.effective_hourly_cost,
            storage_locality=offering.storage_locality,
            cloud_placement=selected,
        ),
        local=local,
        cloud=cloud,
        warnings=("cloud-spillover-selected",),
    )


def create_execution_lease(
    decision: PlacementDecision,
    *,
    attempt: int,
    issued_at: datetime,
    ttl: timedelta = timedelta(minutes=10),
) -> ExecutionLease:
    if not decision.runnable or decision.target is None:
        raise ValueError("Cannot lease a non-runnable placement")
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if ttl <= timedelta(0) or ttl > timedelta(hours=1):
        raise ValueError("lease TTL must be positive and no more than one hour")
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("issued_at must be timezone-aware")
    seed = f"{decision.request.job_id}:{attempt}:{decision.target.identity}"
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return ExecutionLease(
        lease_id=digest[:32],
        job_id=decision.request.job_id,
        target_identity=decision.target.identity,
        attempt=attempt,
        issued_at=issued_at,
        expires_at=issued_at + ttl,
        idempotency_key=f"analysis-lease:{digest}",
    )
