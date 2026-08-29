"""Strict loader for rule-pack deduction ontology data.

No arbitrary expressions or executable callbacks are accepted. The active rule-pack owns
criterion/severity values and camera/evidence requirements; this loader only converts a
reviewed JSON/YAML mapping into the pure deduction contracts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .deductions import (
    DeductionChannel,
    DeductionError,
    DeductionPolicy,
    DeductionRule,
    DeductionScope,
    SeverityRule,
)
from .domain import Apparatus

DEDUCTION_POLICY_SCHEMA_VERSION = "ai.wagvid.deduction-policy.v1"


def deduction_policy_from_mapping(payload: Mapping[str, Any]) -> DeductionPolicy:
    _exact_keys(
        payload,
        required={"schema", "rulepack_id", "rulepack_digest", "apparatus", "units_per_point", "rules"},
        optional=set(),
        context="deduction policy",
    )
    schema = _string(payload["schema"], "schema")
    if schema != DEDUCTION_POLICY_SCHEMA_VERSION:
        raise DeductionError(f"unsupported deduction policy schema: {schema}")
    apparatus_value = _string(payload["apparatus"], "apparatus")
    try:
        apparatus = Apparatus(apparatus_value)
    except ValueError as error:
        raise DeductionError(f"invalid deduction apparatus: {apparatus_value}") from error
    return DeductionPolicy(
        rulepack_id=_string(payload["rulepack_id"], "rulepack_id"),
        rulepack_digest=_string(payload["rulepack_digest"], "rulepack_digest"),
        apparatus=apparatus,
        units_per_point=_integer(payload["units_per_point"], "units_per_point"),
        rules=tuple(_rule(item) for item in _mapping_sequence(payload["rules"], "rules")),
    )


def _rule(payload: Mapping[str, Any]) -> DeductionRule:
    _exact_keys(
        payload,
        required={"rule_id", "channel", "criterion_id", "scope", "severities"},
        optional={
            "required_camera_capabilities",
            "minimum_evidence_quality_milli",
            "minimum_model_confidence_milli",
            "human_judgement_required",
            "source_rule_id",
        },
        context="deduction rule",
    )
    try:
        channel = DeductionChannel(_string(payload["channel"], "rule.channel"))
    except ValueError as error:
        raise DeductionError(f"invalid deduction channel: {payload['channel']}") from error
    try:
        scope = DeductionScope(_string(payload["scope"], "rule.scope"))
    except ValueError as error:
        raise DeductionError(f"invalid deduction scope: {payload['scope']}") from error
    return DeductionRule(
        rule_id=_string(payload["rule_id"], "rule.rule_id"),
        channel=channel,
        criterion_id=_string(payload["criterion_id"], "rule.criterion_id"),
        scope=scope,
        severities=tuple(
            _severity(item) for item in _mapping_sequence(payload["severities"], "rule.severities")
        ),
        required_camera_capabilities=frozenset(
            _string_sequence(
                payload.get("required_camera_capabilities", ()),
                "rule.required_camera_capabilities",
            )
        ),
        minimum_evidence_quality_milli=_integer(
            payload.get("minimum_evidence_quality_milli", 0),
            "rule.minimum_evidence_quality_milli",
        ),
        minimum_model_confidence_milli=_integer(
            payload.get("minimum_model_confidence_milli", 0),
            "rule.minimum_model_confidence_milli",
        ),
        human_judgement_required=_boolean(
            payload.get("human_judgement_required", False),
            "rule.human_judgement_required",
        ),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "rule.source_rule_id"),
    )


def _severity(payload: Mapping[str, Any]) -> SeverityRule:
    _exact_keys(
        payload,
        required={"severity_id", "deduction_units"},
        optional={"source_rule_id"},
        context="severity rule",
    )
    return SeverityRule(
        severity_id=_string(payload["severity_id"], "severity.severity_id"),
        deduction_units=_integer(payload["deduction_units"], "severity.deduction_units"),
        source_rule_id=_optional_string(payload.get("source_rule_id"), "severity.source_rule_id"),
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
        raise DeductionError(f"{context} is missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise DeductionError(f"{context} contains unknown field(s): {', '.join(sorted(unknown))}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeductionError(f"{label} must be an object")
    return value


def _mapping_sequence(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DeductionError(f"{label} must be an array")
    return tuple(_mapping(item, label) for item in value)


def _string_sequence(value: Any, label: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DeductionError(f"{label} must be an array of strings")
    result = tuple(_string(item, label) for item in value)
    if len(result) != len(set(result)):
        raise DeductionError(f"{label} cannot contain duplicate values")
    return result


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeductionError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeductionError(f"{label} must be an integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise DeductionError(f"{label} must be a boolean")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)
