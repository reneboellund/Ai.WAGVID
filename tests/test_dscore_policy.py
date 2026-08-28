from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_wagvid.dscore import DScoreError
from ai_wagvid.dscore_policy import (
    DSCORE_POLICY_SCHEMA_VERSION,
    dscore_policy_from_mapping,
)
from wagvid_rules.validation import load_schema


ROOT = Path(__file__).parents[1]
SCHEMA = load_schema(ROOT / "schemas" / "dscore-policy-v1.schema.json")


def fixture() -> dict:
    return {
        "schema": DSCORE_POLICY_SCHEMA_VERSION,
        "rulepack_id": "fixture-rulepack@v1",
        "rulepack_digest": "a" * 64,
        "apparatus": "BB",
        "units_per_point": 10,
        "max_ambiguity_outcomes": 64,
        "elements": [
            {
                "element_id": "fixture-a",
                "value_units": 1,
                "repetition_key": "rep-a",
                "groups": ["acro", "low"],
                "source_rule_id": "fixture.source.element-a",
            },
            {
                "element_id": "fixture-b",
                "value_units": 3,
                "repetition_key": "rep-b",
                "groups": ["dance", "medium"],
                "source_rule_id": "fixture.source.element-b",
            },
        ],
        "counting": {
            "max_counted_elements": 2,
            "repetition_limit_per_key": 1,
            "quotas": [
                {"group": "acro", "minimum_counted": 1, "maximum_counted": 1},
                {"group": "dance", "minimum_counted": 1, "maximum_counted": 1},
            ],
        },
        "composition": [
            {
                "requirement_id": "fixture.cr",
                "match_group": "dance",
                "minimum_count": 1,
                "award_units": 5,
                "scope": "performed",
                "source_rule_id": "fixture.source.cr",
            }
        ],
        "connections": [
            {
                "rule_id": "fixture.connection",
                "award_units": 2,
                "priority": 10,
                "left_groups_any": ["acro"],
                "right_groups_any": ["dance"],
                "require_adjacent": True,
                "source_rule_id": "fixture.source.connection",
            }
        ],
        "adjustments": [
            {
                "rule_id": "fixture.adjustment",
                "value_units": -1,
                "source_rule_id": "fixture.source.adjustment",
            }
        ],
    }


def test_fixture_is_valid_against_public_declarative_schema():
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(fixture()), key=lambda error: list(error.path))
    assert errors == []


def test_loader_builds_same_reviewable_policy_without_executable_expressions():
    parsed = dscore_policy_from_mapping(fixture())
    assert parsed.rulepack_id == "fixture-rulepack@v1"
    assert parsed.apparatus.value == "BB"
    assert parsed.units_per_point == 10
    assert parsed.elements[0].source_rule_id == "fixture.source.element-a"
    assert parsed.counting.quotas[1].group == "dance"
    assert parsed.connections[0].require_adjacent is True
    assert parsed.adjustments[0].value_units == -1
    assert len(parsed.digest) == 64


def test_unknown_fields_are_rejected_instead_of_becoming_hidden_rule_logic():
    value = fixture()
    value["python_callback"] = "score_everything()"
    with pytest.raises(DScoreError, match="unknown field"):
        dscore_policy_from_mapping(value)

    element = fixture()
    element["elements"][0]["expression"] = "athlete_id == 'x'"
    with pytest.raises(DScoreError, match="unknown field"):
        dscore_policy_from_mapping(element)


def test_wrong_schema_and_invalid_boolean_integer_types_fail_closed():
    wrong_schema = fixture()
    wrong_schema["schema"] = "future-policy-v99"
    with pytest.raises(DScoreError, match="unsupported"):
        dscore_policy_from_mapping(wrong_schema)

    wrong_integer = fixture()
    wrong_integer["units_per_point"] = True
    with pytest.raises(DScoreError, match="must be an integer"):
        dscore_policy_from_mapping(wrong_integer)

    wrong_boolean = fixture()
    wrong_boolean["connections"][0]["require_adjacent"] = 1
    with pytest.raises(DScoreError, match="must be a boolean"):
        dscore_policy_from_mapping(wrong_boolean)


def test_schema_rejects_unknown_fields_and_duplicate_string_sets():
    unknown = fixture()
    unknown["elements"][0]["hidden"] = "not allowed"
    assert list(Draft202012Validator(SCHEMA).iter_errors(unknown))

    duplicate_group = fixture()
    duplicate_group["elements"][0]["groups"] = ["acro", "acro"]
    assert list(Draft202012Validator(SCHEMA).iter_errors(duplicate_group))


def test_rulepack_digest_change_changes_policy_digest_without_changing_rule_values():
    first = dscore_policy_from_mapping(fixture())
    changed = deepcopy(fixture())
    changed["rulepack_digest"] = "b" * 64
    second = dscore_policy_from_mapping(changed)
    assert first.elements == second.elements
    assert first.digest != second.digest
