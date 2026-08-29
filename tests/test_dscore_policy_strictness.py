import pytest

from ai_wagvid.dscore import DScoreError
from ai_wagvid.dscore_policy import dscore_policy_from_mapping


def minimal_policy() -> dict:
    return {
        "schema": "ai.wagvid.dscore-policy.v1",
        "rulepack_id": "fixture@v1",
        "rulepack_digest": "a" * 64,
        "apparatus": "FX",
        "units_per_point": 10,
        "elements": [
            {
                "element_id": "element-a",
                "value_units": 1,
                "repetition_key": "rep-a",
                "groups": ["acro"],
            }
        ],
        "counting": {"max_counted_elements": 1},
    }


def test_numeric_strings_are_not_silently_coerced_into_rule_identifiers():
    value = minimal_policy()
    value["rulepack_id"] = 123
    with pytest.raises(DScoreError, match="rulepack_id must be a non-empty string"):
        dscore_policy_from_mapping(value)

    value = minimal_policy()
    value["elements"][0]["element_id"] = 123
    with pytest.raises(DScoreError, match="element.element_id must be a non-empty string"):
        dscore_policy_from_mapping(value)


def test_duplicate_group_values_fail_in_loader_even_without_json_schema_validation():
    value = minimal_policy()
    value["elements"][0]["groups"] = ["acro", "acro"]
    with pytest.raises(DScoreError, match="duplicate values"):
        dscore_policy_from_mapping(value)


def test_optional_source_rule_id_must_be_a_real_string_when_present():
    value = minimal_policy()
    value["elements"][0]["source_rule_id"] = 42
    with pytest.raises(DScoreError, match="source_rule_id must be a non-empty string"):
        dscore_policy_from_mapping(value)
