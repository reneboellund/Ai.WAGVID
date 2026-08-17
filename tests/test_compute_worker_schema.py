import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "compute-worker-v1.schema.json").read_text())


def test_compute_worker_capability_example_is_valid():
    payload = {
        "schema": "ai.wagvid.compute-worker.v1",
        "worker_id": "local-gpu-1",
        "provider": "local",
        "location": "nivaa",
        "healthy": True,
        "ephemeral": False,
        "queue_depth": 0,
        "active_jobs": 0,
        "hourly_cost": None,
        "storage_locality": ["storage:primary"],
        "model_bundles": ["pose-v1"],
        "devices": [
            {
                "device_id": "cuda:0",
                "backend": "cuda",
                "vendor": "NVIDIA",
                "model": "GeForce RTX fixture",
                "architecture": "fixture",
                "device_index": 0,
                "total_vram_mb": 24576,
                "free_vram_mb": 22000,
                "driver_version": "fixture",
                "runtime_version": "fixture",
                "precisions": ["fp32", "fp16"],
                "capabilities": ["tensor-inference"],
            }
        ],
    }
    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []


def test_compute_worker_rejects_unknown_backend():
    payload = {
        "schema": "ai.wagvid.compute-worker.v1",
        "worker_id": "bad",
        "provider": "local",
        "location": "local",
        "healthy": True,
        "model_bundles": [],
        "devices": [
            {
                "device_id": "x",
                "backend": "marketing-magic",
                "vendor": "unknown",
                "model": "unknown",
                "precisions": ["fp32"],
                "capabilities": [],
            }
        ],
    }
    assert list(Draft202012Validator(SCHEMA).iter_errors(payload))
