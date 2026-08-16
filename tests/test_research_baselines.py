import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]


def test_research_baseline_registry_is_valid() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "research-baselines-v1.schema.json").read_text(encoding="utf-8")
    )
    registry = yaml.safe_load(
        (ROOT / "research" / "baselines.yaml").read_text(encoding="utf-8")
    )
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(registry)
    )
    assert errors == []


def test_unresolved_finegrade_license_blocks_direct_adoption() -> None:
    registry = yaml.safe_load(
        (ROOT / "research" / "baselines.yaml").read_text(encoding="utf-8")
    )
    finegrade = next(item for item in registry["candidates"] if item["id"] == "finegrade")
    assert finegrade["status"] == "research-hold"
    assert finegrade["license_status"] == "unresolved"


def test_first_pose_spike_is_explicit() -> None:
    registry = yaml.safe_load(
        (ROOT / "research" / "baselines.yaml").read_text(encoding="utf-8")
    )
    approved = [item["id"] for item in registry["candidates"] if item["status"] == "approved-for-spike"]
    assert approved == ["mmpose-rtmpose"]
