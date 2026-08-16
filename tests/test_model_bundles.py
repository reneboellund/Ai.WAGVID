from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from ai_wagvid.model_bundles import ModelBundleError, load_model_catalog, resolve_profile

CATALOG = Path("config/model-bundles.yaml")
SCHEMA = Path("schemas/model-bundles-v1.schema.json")


def load():
    return load_model_catalog(CATALOG, schema_path=SCHEMA)


def write(tmp_path, value):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    return path


def test_contract_catalog_is_valid_but_not_misrepresented_as_runnable():
    profile = resolve_profile(load(), "competition-research-contract@1")
    assert profile.mode == "judge-research"
    assert profile.runnable is False
    assert {item["capability"] for item in profile.components} == {
        "perception",
        "action",
        "interpretation",
        "quality",
    }


def test_unknown_component_and_incomplete_profile_fail_closed(tmp_path):
    value = deepcopy(load())
    value["profiles"][0]["components"][0] = "missing@1"
    with pytest.raises(ModelBundleError, match="unknown components"):
        load_model_catalog(write(tmp_path, value), schema_path=SCHEMA)

    value = deepcopy(load())
    value["profiles"][0]["components"] = [
        "pose-contract@1",
        "action-contract@1",
        "aqa-contract@1",
    ]
    with pytest.raises(ModelBundleError, match="lacks required"):
        load_model_catalog(write(tmp_path, value), schema_path=SCHEMA)


def test_duplicate_ids_and_unknown_profile_fail_closed(tmp_path):
    value = deepcopy(load())
    value["components"].append(deepcopy(value["components"][0]))
    with pytest.raises(ModelBundleError, match="unique"):
        load_model_catalog(write(tmp_path, value), schema_path=SCHEMA)
    with pytest.raises(ModelBundleError, match="unknown model profile"):
        resolve_profile(load(), "not-configured")
