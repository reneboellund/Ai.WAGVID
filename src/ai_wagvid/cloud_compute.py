"""Cloud GPU offering, policy and placement contracts for AWS/Azure/GCP.

Provider API adapters enumerate current offerings/quota and convert them to these
records. Selection remains deterministic and independent of provider SDK objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Protocol

from .compute_runtime import ComputeBackend, ExecutionRequirement, Precision


class CloudProvider(StrEnum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


@dataclass(frozen=True)
class CloudGpuOffering:
    provider: CloudProvider
    region: str
    zone: str | None
    sku: str
    accelerator_model: str
    backend: ComputeBackend
    vram_mb: int
    precisions: frozenset[Precision]
    capabilities: frozenset[str] = frozenset()
    available: bool = True
    quota_available: bool = True
    hourly_cost: float | None = None
    spot_hourly_cost: float | None = None
    storage_locality: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CloudComputePolicy:
    enabled_providers: frozenset[CloudProvider]
    allowed_regions: dict[CloudProvider, frozenset[str]]
    allowed_sku_prefixes: dict[CloudProvider, tuple[str, ...]]
    max_hourly_cost: float | None = None
    allow_spot: bool = False
    max_workers: int = 1

    def __post_init__(self):
        if self.max_workers < 1:
            raise ValueError("max_workers must be positive")
        if self.max_hourly_cost is not None and self.max_hourly_cost < 0:
            raise ValueError("max_hourly_cost cannot be negative")


@dataclass(frozen=True)
class CloudPlacement:
    offering: CloudGpuOffering
    use_spot: bool
    effective_hourly_cost: float | None
    score: tuple


@dataclass(frozen=True)
class CloudPlacementDecision:
    selected: CloudPlacement | None
    rejected: tuple[tuple[str, str], ...]


class CloudComputeControl(Protocol):
    """Control-plane shape implemented separately by AWS/Azure/GCP adapters."""

    provider: CloudProvider

    def validate_connection(self) -> dict: ...

    def list_gpu_offerings(self) -> Iterable[CloudGpuOffering]: ...

    def provision_worker(self, placement: CloudPlacement, *, idempotency_key: str) -> str: ...

    def drain_worker(self, worker_id: str) -> None: ...

    def delete_worker(self, worker_id: str) -> None: ...


def _sku_allowed(offering: CloudGpuOffering, policy: CloudComputePolicy) -> bool:
    prefixes = policy.allowed_sku_prefixes.get(offering.provider, ())
    return not prefixes or offering.sku.startswith(prefixes)


def choose_cloud_placement(
    offerings: Iterable[CloudGpuOffering],
    requirement: ExecutionRequirement,
    policy: CloudComputePolicy,
    *,
    prefer_spot: bool = False,
) -> CloudPlacementDecision:
    candidates: list[CloudPlacement] = []
    rejected: list[tuple[str, str]] = []
    provider_order = [CloudProvider.AWS, CloudProvider.AZURE, CloudProvider.GCP]

    for offering in offerings:
        identity = f"{offering.provider.value}:{offering.region}:{offering.sku}"
        reason = None
        if offering.provider not in policy.enabled_providers:
            reason = "provider-disabled"
        elif offering.region not in policy.allowed_regions.get(offering.provider, frozenset()):
            reason = "region-not-allowed"
        elif not _sku_allowed(offering, policy):
            reason = "sku-not-allowed"
        elif not offering.available:
            reason = "capacity-unavailable"
        elif not offering.quota_available:
            reason = "quota-unavailable"
        elif offering.backend not in requirement.allowed_backends:
            reason = "backend-incompatible"
        elif offering.vram_mb < requirement.minimum_vram_mb:
            reason = "insufficient-vram"
        elif not requirement.allowed_precisions.intersection(offering.precisions):
            reason = "precision-incompatible"
        elif not requirement.required_capabilities.issubset(offering.capabilities):
            reason = "capability-missing"
        elif requirement.require_storage_locality and requirement.storage_locality not in (
            offering.storage_locality
        ):
            reason = "storage-locality-required"

        use_spot = bool(prefer_spot and policy.allow_spot and offering.spot_hourly_cost is not None)
        effective_cost = offering.spot_hourly_cost if use_spot else offering.hourly_cost
        cost_limit = requirement.max_hourly_cost
        if cost_limit is None:
            cost_limit = policy.max_hourly_cost
        elif policy.max_hourly_cost is not None:
            cost_limit = min(cost_limit, policy.max_hourly_cost)
        if reason is None and cost_limit is not None:
            if effective_cost is None:
                reason = "cost-unknown"
            elif effective_cost > cost_limit:
                reason = "cost-guard"

        if reason:
            rejected.append((identity, reason))
            continue

        locality_penalty = 0
        if requirement.storage_locality:
            locality_penalty = int(requirement.storage_locality not in offering.storage_locality)
        provider_rank = provider_order.index(offering.provider)
        cost_rank = effective_cost if effective_cost is not None else float("inf")
        score = (
            locality_penalty,
            provider_rank,
            cost_rank,
            offering.region,
            offering.zone or "",
            offering.sku,
        )
        candidates.append(CloudPlacement(offering, use_spot, effective_cost, score))

    candidates.sort(key=lambda item: item.score)
    rejected.sort()
    return CloudPlacementDecision(candidates[0] if candidates else None, tuple(rejected))
