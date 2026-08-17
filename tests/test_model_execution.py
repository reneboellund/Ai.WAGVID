import pytest

from ai_wagvid.compute_runtime import ComputeBackend, Precision
from ai_wagvid.model_execution import (
    ModelExecutionError,
    component_execution,
    profile_execution_requirement,
)


def component(
    component_id,
    *,
    backends=("cuda", "rocm"),
    precisions=("fp16", "fp32"),
    minimum_vram_mb=8000,
    recommended_vram_mb=12000,
    cpu_fallback=False,
    validated=True,
    required_capabilities=(),
):
    return {
        "id": component_id,
        "execution": {
            "backends": list(backends),
            "precisions": list(precisions),
            "minimum_vram_mb": minimum_vram_mb,
            "recommended_vram_mb": recommended_vram_mb,
            "cpu_fallback": cpu_fallback,
            "validated": validated,
            "required_capabilities": list(required_capabilities),
            "validation_reference": "benchmark://fixture",
        },
    }


def test_component_execution_fails_closed_when_metadata_is_missing():
    with pytest.raises(ModelExecutionError, match="no execution contract"):
        component_execution({"id": "pose@1"})


def test_component_execution_requires_validation_by_default():
    with pytest.raises(ModelExecutionError, match="not validated"):
        component_execution(component("pose@1", validated=False))
    parsed = component_execution(component("pose@1", validated=False), require_validated=False)
    assert parsed.validated is False


def test_profile_requirement_intersects_backends_and_precision():
    requirement = profile_execution_requirement(
        profile_id="profile@1",
        components=[
            component(
                "pose@1",
                backends=("cuda", "rocm"),
                precisions=("fp16", "fp32"),
                minimum_vram_mb=12000,
            ),
            component(
                "action@1",
                backends=("cuda",),
                precisions=("fp16",),
                minimum_vram_mb=16000,
            ),
        ],
        preferred_backends=(ComputeBackend.CUDA, ComputeBackend.ROCM),
    )
    assert requirement.allowed_backends == frozenset({ComputeBackend.CUDA})
    assert requirement.allowed_precisions == frozenset({Precision.FP16})
    assert requirement.minimum_vram_mb == 16000


def test_profile_requirement_rejects_no_common_backend():
    with pytest.raises(ModelExecutionError, match="no common compute backend"):
        profile_execution_requirement(
            profile_id="mixed@1",
            components=[
                component("pose@1", backends=("cuda",)),
                component("action@1", backends=("rocm",)),
            ],
        )


def test_cpu_fallback_requires_every_component_to_allow_it():
    requirement = profile_execution_requirement(
        profile_id="cpu@1",
        components=[
            component("pose@1", backends=("cpu", "cuda"), cpu_fallback=True),
            component("action@1", backends=("cpu", "cuda"), cpu_fallback=False),
        ],
    )
    assert requirement.allow_cpu_fallback is False


def test_profile_unions_required_runtime_capabilities():
    requirement = profile_execution_requirement(
        profile_id="capability@1",
        components=[
            component("pose@1", required_capabilities=("tensor-inference",)),
            component("action@1", required_capabilities=("video-decode",)),
        ],
    )
    assert requirement.required_capabilities == frozenset(
        {"tensor-inference", "video-decode"}
    )


def test_invalid_recommended_vram_is_rejected():
    with pytest.raises(ModelExecutionError, match="invalid minimum/recommended VRAM"):
        component_execution(
            component(
                "bad@1",
                minimum_vram_mb=16000,
                recommended_vram_mb=8000,
            )
        )
