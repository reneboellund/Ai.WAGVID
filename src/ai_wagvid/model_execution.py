"""Translate model-bundle execution metadata into compute scheduler requirements.

Execution metadata is optional in the v1 catalog for backward compatibility, but a
production scheduler fails closed when a runnable component has no validated execution
contract. This prevents marketing/device-name guesses from becoming runtime policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .compute_runtime import ComputeBackend, ExecutionRequirement, Precision


class ModelExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentExecution:
    component_id: str
    backends: frozenset[ComputeBackend]
    precisions: frozenset[Precision]
    minimum_vram_mb: int
    recommended_vram_mb: int
    cpu_fallback: bool
    required_capabilities: frozenset[str]
    validated: bool
    validation_reference: str | None = None


def _parse_backend(value: str) -> ComputeBackend:
    try:
        return ComputeBackend(value)
    except ValueError as exc:
        raise ModelExecutionError(f"Unsupported compute backend in model bundle: {value}") from exc


def _parse_precision(value: str) -> Precision:
    try:
        return Precision(value)
    except ValueError as exc:
        raise ModelExecutionError(f"Unsupported precision in model bundle: {value}") from exc


def component_execution(component: dict[str, Any], *, require_validated: bool = True) -> ComponentExecution:
    metadata = component.get("execution")
    component_id = str(component.get("id", "<unknown>"))
    if not isinstance(metadata, dict):
        raise ModelExecutionError(f"Component {component_id} has no execution contract")
    backends = frozenset(_parse_backend(str(value)) for value in metadata.get("backends", []))
    precisions = frozenset(_parse_precision(str(value)) for value in metadata.get("precisions", []))
    if not backends or not precisions:
        raise ModelExecutionError(f"Component {component_id} execution contract is incomplete")
    minimum_vram = int(metadata.get("minimum_vram_mb", 0))
    recommended_vram = int(metadata.get("recommended_vram_mb", minimum_vram))
    if minimum_vram < 0 or recommended_vram < minimum_vram:
        raise ModelExecutionError(
            f"Component {component_id} has invalid minimum/recommended VRAM requirements"
        )
    validated = bool(metadata.get("validated", False))
    if require_validated and not validated:
        raise ModelExecutionError(f"Component {component_id} execution contract is not validated")
    return ComponentExecution(
        component_id=component_id,
        backends=backends,
        precisions=precisions,
        minimum_vram_mb=minimum_vram,
        recommended_vram_mb=recommended_vram,
        cpu_fallback=bool(metadata.get("cpu_fallback", False)),
        required_capabilities=frozenset(
            str(value) for value in metadata.get("required_capabilities", [])
        ),
        validated=validated,
        validation_reference=metadata.get("validation_reference"),
    )


def profile_execution_requirement(
    *,
    profile_id: str,
    components: Iterable[dict[str, Any]],
    require_validated: bool = True,
    preferred_backends: tuple[ComputeBackend, ...] = (),
    preferred_providers: tuple[str, ...] = (),
    storage_locality: str | None = None,
    require_storage_locality: bool = False,
    allow_cloud: bool = True,
    max_hourly_cost: float | None = None,
) -> ExecutionRequirement:
    """Aggregate component contracts into a fail-closed profile requirement.

    A worker must support a backend/precision common to every model component in the
    profile. VRAM uses the largest component floor because v1 runs stages sequentially;
    a later concurrent pipeline must declare a separate memory model rather than sum
    these values silently.
    """
    execution = [
        component_execution(component, require_validated=require_validated)
        for component in components
    ]
    if not execution:
        raise ModelExecutionError(f"Profile {profile_id} has no components")

    common_backends = set(execution[0].backends)
    common_precisions = set(execution[0].precisions)
    for item in execution[1:]:
        common_backends.intersection_update(item.backends)
        common_precisions.intersection_update(item.precisions)
    if not common_backends:
        raise ModelExecutionError(f"Profile {profile_id} has no common compute backend")
    if not common_precisions:
        raise ModelExecutionError(f"Profile {profile_id} has no common precision")

    allow_cpu_fallback = all(item.cpu_fallback for item in execution)
    required_capabilities = frozenset().union(
        *(item.required_capabilities for item in execution)
    )
    minimum_vram = max(item.minimum_vram_mb for item in execution)
    return ExecutionRequirement(
        model_bundle=profile_id,
        allowed_backends=frozenset(common_backends),
        allowed_precisions=frozenset(common_precisions),
        minimum_vram_mb=minimum_vram,
        preferred_backends=preferred_backends,
        preferred_providers=preferred_providers,
        storage_locality=storage_locality,
        require_storage_locality=require_storage_locality,
        allow_cpu_fallback=allow_cpu_fallback,
        allow_cloud=allow_cloud,
        max_hourly_cost=max_hourly_cost,
        required_capabilities=required_capabilities,
    )
