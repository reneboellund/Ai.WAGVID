import json

from ai_wagvid.compute_discovery import (
    discover_amd_rocm,
    discover_nvidia,
    discover_openvino_gpus,
)
from ai_wagvid.compute_runtime import ComputeBackend


def test_nvidia_discovery_parses_multiple_devices_without_running_vendor_sdk():
    output = (
        "0, NVIDIA GeForce RTX Fixture, 999.1, 24576, 20000\n"
        "1, NVIDIA L4, 999.1, 23034, 21000\n"
    )
    result = discover_nvidia(runner=lambda command: output)
    assert result.available is True
    assert [device.device_id for device in result.devices] == ["cuda:0", "cuda:1"]
    assert result.devices[0].total_vram_mb == 24576
    assert result.devices[1].model == "NVIDIA L4"


def test_nvidia_discovery_fails_closed_when_probe_is_missing():
    def missing(command):
        raise FileNotFoundError("nvidia-smi")

    result = discover_nvidia(runner=missing)
    assert result.available is False
    assert result.devices == ()
    assert "unavailable" in (result.reason or "")


def test_rocm_discovery_parses_common_json_card_map():
    payload = {
        "card0": {
            "Card series": "AMD Radeon PRO Fixture",
            "VRAM Total Memory (B)": "17179869184",
            "VRAM Total Used Memory (B)": "2147483648",
            "Driver version": "fixture-driver",
        }
    }
    result = discover_amd_rocm(runner=lambda command: json.dumps(payload))
    assert result.available is True
    device = result.devices[0]
    assert device.device_id == "rocm:0"
    assert device.total_vram_mb == 16384
    assert device.free_vram_mb == 14336
    assert device.backend == ComputeBackend.ROCM


def test_rocm_discovery_reports_invalid_json_instead_of_guessing():
    result = discover_amd_rocm(runner=lambda command: "not-json")
    assert result.available is False
    assert "probe failed" in (result.reason or "")


class FakeOpenVinoCore:
    available_devices = ["CPU", "GPU.0", "GPU.1"]

    def get_property(self, device, key):
        assert key == "FULL_DEVICE_NAME"
        return {"GPU.0": "Intel Arc Fixture", "GPU.1": "Intel Flex Fixture"}[device]


def test_openvino_discovery_only_registers_gpu_devices():
    result = discover_openvino_gpus(core_factory=FakeOpenVinoCore)
    assert result.available is True
    assert [device.model for device in result.devices] == [
        "Intel Arc Fixture",
        "Intel Flex Fixture",
    ]
    assert all(device.backend == ComputeBackend.OPENVINO_GPU for device in result.devices)


def test_openvino_missing_runtime_is_reported_not_import_time_dependency():
    def unavailable():
        raise RuntimeError("runtime unavailable")

    result = discover_openvino_gpus(core_factory=unavailable)
    assert result.available is False
    assert result.devices == ()
