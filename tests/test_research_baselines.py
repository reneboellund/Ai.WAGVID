import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]


def load_registry() -> dict:
    return yaml.safe_load(
        (ROOT / "research" / "baselines.yaml").read_text(encoding="utf-8")
    )


def test_research_baseline_registry_is_valid() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "research-baselines-v1.schema.json").read_text(encoding="utf-8")
    )
    errors = list(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(load_registry())
    )
    assert errors == []


def test_usage_is_internal_non_commercial_and_non_redistributive() -> None:
    usage = load_registry()["usage_profile"]
    assert usage["deployment_class"] == "internal-non-commercial-research"
    assert usage["commercial_use"] is False
    assert usage["external_service"] is False
    assert usage["public_dataset_redistribution"] is False


def test_unresolved_finegrade_license_blocks_direct_adoption() -> None:
    finegrade = next(
        item for item in load_registry()["candidates"] if item["id"] == "finegrade"
    )
    assert finegrade["status"] == "research-hold"
    assert finegrade["license_status"] == "unresolved"


def test_athletepose3d_is_allowed_only_for_internal_research() -> None:
    athletepose = next(
        item for item in load_registry()["candidates"] if item["id"] == "athletepose3d"
    )
    assert athletepose["status"] == "internal-research-allowed"
    assert athletepose["license_status"] == "non-commercial-research-only"


def test_first_pose_software_spike_is_explicit() -> None:
    approved = [
        item["id"]
        for item in load_registry()["candidates"]
        if item["status"] == "approved-for-spike"
    ]
    assert approved == ["mmpose-rtmpose"]
