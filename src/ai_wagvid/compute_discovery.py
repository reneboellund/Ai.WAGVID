"""Local accelerator discovery adapters.

Discovery is intentionally optional and fail-closed. Importing Ai.WAGVID never requires
CUDA, ROCm or OpenVINO. Callers may inject command execution for tests; production
workers run probes explicitly during registration/heartbeat.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

from .compute_runtime import AcceleratorDevice, ComputeBackend, Precision


CommandRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class DiscoveryResult:
    backend: ComputeBackend
    devices: tuple[AcceleratorDevice, ...] = ()
    available: bool = False
    reason: str | None = None


def _default_runner(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout


def _int_or_none(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"n/a", "na", "none", "unknown"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def discover_nvidia(*, runner: CommandRunner = _default_runner) -> DiscoveryResult:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,driver_version,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = runner(command)
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        return DiscoveryResult(ComputeBackend.CUDA, reason=f"nvidia-smi unavailable: {exc}")
    devices: list[AcceleratorDevice] = []
    for row in csv.reader(io.StringIO(output)):
        if not row or len(row) < 5:
            continue
        index = _int_or_none(row[0])
        if index is None:
            continue
        name = row[1].strip()
        driver = row[2].strip() or None
        total = _int_or_none(row[3])
        free = _int_or_none(row[4])
        devices.append(
            AcceleratorDevice(
                device_id=f"cuda:{index}",
                backend=ComputeBackend.CUDA,
                vendor="NVIDIA",
                model=name or "Unknown NVIDIA GPU",
                device_index=index,
                total_vram_mb=total,
                free_vram_mb=free,
                driver_version=driver,
                precisions=frozenset({Precision.FP32, Precision.FP16}),
                capabilities=frozenset({"cuda"}),
            )
        )
    if not devices:
        return DiscoveryResult(ComputeBackend.CUDA, reason="nvidia-smi reported no usable GPUs")
    return DiscoveryResult(ComputeBackend.CUDA, tuple(devices), available=True)


def discover_amd_rocm(*, runner: CommandRunner = _default_runner) -> DiscoveryResult:
    """Discover ROCm devices from `rocm-smi --json` without assuming unsupported SKUs.

    ROCm JSON keys have varied between releases, so the parser accepts common card
    maps and only publishes data that can be identified safely. Model/runtime support
    remains a separate compatibility gate.
    """
    command = [
        "rocm-smi",
        "--showproductname",
        "--showmeminfo",
        "vram",
        "--showdriverversion",
        "--json",
    ]
    try:
        output = runner(command)
        payload = json.loads(output)
    except FileNotFoundError as exc:
        return DiscoveryResult(ComputeBackend.ROCM, reason=f"rocm-smi unavailable: {exc}")
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        return DiscoveryResult(ComputeBackend.ROCM, reason=f"ROCm probe failed: {exc}")

    cards = payload if isinstance(payload, dict) else {}
    devices: list[AcceleratorDevice] = []
    for key, values in sorted(cards.items()):
        if not isinstance(values, dict) or not str(key).casefold().startswith("card"):
            continue
        digits = "".join(character for character in str(key) if character.isdigit())
        index = int(digits) if digits else len(devices)
        normalized = {str(name).casefold(): value for name, value in values.items()}
        model = next(
            (
                str(value).strip()
                for name, value in normalized.items()
                if "card series" in name or "card model" in name or "product name" in name
            ),
            "Unknown AMD GPU",
        )
        driver = next(
            (str(value).strip() for name, value in normalized.items() if "driver version" in name),
            None,
        )
        total_bytes = next(
            (
                _int_or_none(value)
                for name, value in normalized.items()
                if "vram total" in name
            ),
            None,
        )
        used_bytes = next(
            (
                _int_or_none(value)
                for name, value in normalized.items()
                if "vram used" in name
            ),
            None,
        )
        total_mb = total_bytes // (1024 * 1024) if total_bytes is not None else None
        free_mb = None
        if total_bytes is not None and used_bytes is not None:
            free_mb = max(total_bytes - used_bytes, 0) // (1024 * 1024)
        devices.append(
            AcceleratorDevice(
                device_id=f"rocm:{index}",
                backend=ComputeBackend.ROCM,
                vendor="AMD",
                model=model,
                device_index=index,
                total_vram_mb=total_mb,
                free_vram_mb=free_mb,
                driver_version=driver,
                precisions=frozenset({Precision.FP32, Precision.FP16}),
                capabilities=frozenset({"rocm"}),
            )
        )
    if not devices:
        return DiscoveryResult(ComputeBackend.ROCM, reason="rocm-smi reported no usable GPUs")
    return DiscoveryResult(ComputeBackend.ROCM, tuple(devices), available=True)


def discover_openvino_gpus(*, core_factory=None) -> DiscoveryResult:
    """Enumerate Intel GPU devices through optional OpenVINO runtime."""
    try:
        if core_factory is None:
            from openvino import Core  # type: ignore[import-not-found]

            core = Core()
        else:
            core = core_factory()
    except (ImportError, RuntimeError, OSError) as exc:
        return DiscoveryResult(
            ComputeBackend.OPENVINO_GPU,
            reason=f"OpenVINO runtime unavailable: {exc}",
        )

    devices: list[AcceleratorDevice] = []
    for available_id in getattr(core, "available_devices", []):
        device_name = str(available_id)
        if not device_name.upper().startswith("GPU"):
            continue
        try:
            model = str(core.get_property(device_name, "FULL_DEVICE_NAME"))
        except Exception:  # optional runtime properties vary by OpenVINO/device generation
            model = device_name
        devices.append(
            AcceleratorDevice(
                device_id=f"openvino:{device_name}",
                backend=ComputeBackend.OPENVINO_GPU,
                vendor="Intel",
                model=model,
                precisions=frozenset({Precision.FP32, Precision.FP16, Precision.INT8}),
                capabilities=frozenset({"openvino-inference"}),
            )
        )
    if not devices:
        return DiscoveryResult(
            ComputeBackend.OPENVINO_GPU,
            reason="OpenVINO reported no GPU devices",
        )
    return DiscoveryResult(ComputeBackend.OPENVINO_GPU, tuple(devices), available=True)
