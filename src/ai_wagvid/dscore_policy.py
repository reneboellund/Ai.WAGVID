"""Strict loader for the declarative D-score policy artifact.

The loader is intentionally small and rejects unknown fields. Rule packs are reviewed data,
not executable configuration: no expressions, imports, callbacks or arbitrary Python are
accepted here. Complex future exceptions must use an explicitly reviewed plugin boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .domain import Apparatus
from .dscore import (
    AdjustmentRule,
    CompositionRequirement,
    ConnectionRule,
    CountingPolicy,
    CountingQuota,
    DScoreError,
    DScorePolicy,
    ElementRule,
)


DSCORE_POLICY_SCHEMA_VERSION = "ai.wagvid.dscore-policy.v1"


def dscore_policy_from_mapping(payload: Mapping[str, Any]) -> DScorePolicy:
    _exact_keys(
        payload,
        required={
            "schema",
            "rulepack_id",
            "rulepack_digest",
            "apparatus",
            "units_per_point",
            "elements",
            "counting",
        },
        optional={"composition", "connections", "adjustments", "max_ambiguity_outcomes"},
        context="D-score policy",
    )
    schema = _string(payload["schema"], "schema")
    if schema != DSCORE_POLICY_SCHEMA_VERSION:
        raise DScoreError(f"unsupported D-score policy schema: {schema}")
    apparatus_value = _string(payload["apparatus"], "apparatus")
    try:
        apparatus = Apparatus(apparatus_value)
    except ValueError as error:
        raise DScoreError(f"invalid D-score apparatus: {apparatus_value}") from error

    elements = tuple(_element_rule(item) for item in _mapping_sequence(payload["elements"], "elements"))
    counting = _counting_policy(_mapping(payload["counting"], "counting"))
    composition = tuple(
        _composition_requirement(item)
        for item in _mapping_sequence(payload.get("composition", ()), "composition")
    )
    connections = tuple(
        _connection_rule(item)
        for item in _mapping_sequence(payload.get("connections", ()), "connections")
    )
    adjustments = tuple(
        _adjustment_rule(item)
        for item in _mapping_sequence(payload.get("adjustments", ()), "adjustments")
    )
    return DScorePolicy(
        rulepack_id=_string(payload["rulepack_id"], "rulepack_id"),
        rulepack_digest=_string(payload["rulepack_digest"], "rulepack_digest"),
        apparatus=apparatus,
        units_per_point=_integer(payload["units_per_point"], "units_per_point"),
        elements=elements,
        counting=counting,
        composition=composition,
        connections=connections,
        adjustments=adjustments,
        max_ambiguity_outcomes=_integer(
            payload.get("max_ambiguity_outcomes", 256), "max_ambiguity_outcomes"
        ),
    )


def _element_rule(payload: Mapping[str, Any]) -> ElementRule:
    _exact_keys(
        payload,
        required={"element_id", "value_units", "repetition_key"},
        optional={"groups", "source_rule_id"},
        context="element rule",
    )
    return ElementRule(
        element_id=_string(payload["element_id"], "element.element_id"),
        value_units=_integer(payload["value_units"], "element.value_units"),
        repetition_key=_string(payload["repetition_key"], "element.repetition_key"),
        groups=frozenset(_string_sequence(payload.get("groups", ()), "element.groups")),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "element.source_rule_id"),
    )


def _counting_policy(payload: Mapping[str, Any]) -> CountingPolicy:
    _exact_keys(
        payload,
        required={"max_counted_elements"},
        optional={"repetition_limit_per_key", "quotas"},
        context="counting policy",
    )
    maximum = payload["max_counted_elements"]
    return CountingPolicy(
        max_counted_elements=(
            None if maximum is None else _integer(maximum, "counting.max_counted_elements")
        ),
        repetition_limit_per_key=_integer(
            payload.get("repetition_limit_per_key", 1), "counting.repetition_limit_per_key"
        ),
        quotas=tuple(
            _counting_quota(item)
            for item in _mapping_sequence(payload.get("quotas", ()), "counting.quotas")
        ),
    )


def _counting_quota(payload: Mapping[str, Any]) -> CountingQuota:
    _exact_keys(
        payload,
        required={"group"},
        optional={"minimum_counted", "maximum_counted"},
        context="counting quota",
    )
    maximum = payload.get("maximum_counted")
    return CountingQuota(
        group=_string(payload["group"], "quota.group"),
        minimum_counted=_integer(payload.get("minimum_counted", 0), "quota.minimum_counted"),
        maximum_counted=(
            None if maximum is None else _integer(maximum, "quota.maximum_counted")
        ),
    )


def _composition_requirement(payload: Mapping[str, Any]) -> CompositionRequirement:
    _exact_keys(
        payload,
        required={"requirement_id", "match_group", "minimum_count", "award_units"},
        optional={"scope", "source_rule_id"},
        context="composition requirement",
    )
    return CompositionRequirement(
        requirement_id=_string(payload["requirement_id"], "composition.requirement_id"),
        match_group=_string(payload["match_group"], "composition.match_group"),
        minimum_count=_integer(payload["minimum_count"], "composition.minimum_count"),
        award_units=_integer(payload["award_units"], "composition.award_units"),
        scope=_string(payload.get("scope", "performed"), "composition.scope"),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "composition.source_rule_id"),
    )


def _connection_rule(payload: Mapping[str, Any]) -> ConnectionRule:
    _exact_keys(
        payload,
        required={"rule_id", "award_units"},
        optional={
            "priority",
            "left_groups_any",
            "right_groups_any",
            "left_element_ids",
            "right_element_ids",
            "require_adjacent",
            "source_rule_id",
        },
        context="connection rule",
    )
    return ConnectionRule(
        rule_id=_string(payload["rule_id"], "connection.rule_id"),
        award_units=_integer(payload["award_units"], "connection.award_units"),
        priority=_integer(payload.get("priority", 0), "connection.priority"),
        left_groups_any=frozenset(
            _string_sequence(payload.get("left_groups_any", ()), "connection.left_groups_any")
        ),
        right_groups_any=frozenset(
            _string_sequence(payload.get("right_groups_any", ()), "connection.right_groups_any")
        ),
        left_element_ids=frozenset(
            _string_sequence(payload.get("left_element_ids", ()), "connection.left_element_ids")
        ),
        right_element_ids=frozenset(
            _string_sequence(payload.get("right_element_ids", ()), "connection.right_element_ids")
        ),
        require_adjacent=_boolean(payload.get("require_adjacent", True), "connection.require_adjacent"),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "connection.source_rule_id"),
    )


def _adjustment_rule(payload: Mapping[str, Any]) -> AdjustmentRule:
    _exact_keys(
        payload,
        required={"rule_id", "value_units"},
        optional={"source_rule_id"},
        context="adjustment rule",
    )
    return AdjustmentRule(
        rule_id=_string(payload["rule_id"], "adjustment.rule_id"),
        value_units=_integer(payload["value_units"], "adjustment.value_units"),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "adjustment.source_rule_id"),
    )


def _exact_keys(
    payload: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    context: str,
) -> None:
    missing = required - set(payload)
    unknown = set(payload) - required - optional
    if missing:
        raise DScoreError(f"{context} is missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise DScoreError(f"{context} contains unknown field(s): {', '.join(sorted(unknown))}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DScoreError(f"{label} must be an object")
    return value


def _mapping_sequence(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DScoreError(f"{label} must be an array")
    return tuple(_mapping(item, label) for item in value)


def _string_sequence(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DScoreError(f"{label} must be an array of strings")
    result = tuple(_string(item, label) for item in value)
    if len(result) != len(set(result)):
        raise DScoreError(f"{label} cannot contain duplicate values")
    return result


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DScoreError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DScoreError(f"{label} must be an integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise DScoreError(f"{label} must be a boolean")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)
