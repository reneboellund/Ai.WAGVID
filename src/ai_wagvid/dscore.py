"""Deterministic, data-driven D-score construction.

This module contains no FIG/WAG scoring values. A pinned rule-pack supplies element
values, counting constraints, composition requirements, connection rules and explicit
adjustments. The engine consumes accepted gymnastics facts only; it never calls ML and
never reads official scores.

Score arithmetic uses integer units defined by the rule-pack (for example 10 units per
point). This keeps normalized ledgers byte-stable and avoids binary floating-point drift.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from math import prod

from .domain import Apparatus


class DScoreError(ValueError):
    pass


class CountReason(StrEnum):
    COUNTED = "counted"
    REPETITION = "repetition"
    COUNT_LIMIT = "count-limit"
    GROUP_QUOTA = "group-quota"
    LOWER_VALUE_SELECTION = "lower-value-selection"


class CompositionStatus(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"


class ConnectionStatus(StrEnum):
    AWARDED = "awarded"
    INTERRUPTED = "interrupted"
    NOT_ADJACENT = "not-adjacent"
    NO_MATCHING_RULE = "no-matching-rule"


@dataclass(frozen=True)
class ElementRule:
    element_id: str
    value_units: int
    repetition_key: str
    groups: frozenset[str] = frozenset()
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.element_id or not self.repetition_key:
            raise DScoreError("element_id and repetition_key are required")
        if self.value_units < 0:
            raise DScoreError("element difficulty value cannot be negative")
        if any(not group.strip() for group in self.groups):
            raise DScoreError("element groups cannot contain empty values")


@dataclass(frozen=True)
class CountingQuota:
    group: str
    minimum_counted: int = 0
    maximum_counted: int | None = None

    def __post_init__(self) -> None:
        if not self.group or self.minimum_counted < 0:
            raise DScoreError("counting quota group/minimum is invalid")
        if self.maximum_counted is not None and (
            self.maximum_counted < 0 or self.maximum_counted < self.minimum_counted
        ):
            raise DScoreError("counting quota maximum is invalid")


@dataclass(frozen=True)
class CountingPolicy:
    max_counted_elements: int | None
    repetition_limit_per_key: int = 1
    quotas: tuple[CountingQuota, ...] = ()

    def __post_init__(self) -> None:
        if self.max_counted_elements is not None and self.max_counted_elements < 0:
            raise DScoreError("max_counted_elements cannot be negative")
        if self.repetition_limit_per_key < 1:
            raise DScoreError("repetition_limit_per_key must be positive")
        groups = [quota.group for quota in self.quotas]
        if len(groups) != len(set(groups)):
            raise DScoreError("counting quota groups must be unique")


@dataclass(frozen=True)
class CompositionRequirement:
    requirement_id: str
    match_group: str
    minimum_count: int
    award_units: int
    scope: str = "performed"
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.requirement_id or not self.match_group or self.minimum_count < 1:
            raise DScoreError("composition requirement identity/group/minimum is invalid")
        if self.award_units < 0:
            raise DScoreError("composition award cannot be negative")
        if self.scope not in {"performed", "counted"}:
            raise DScoreError("composition scope must be performed or counted")


@dataclass(frozen=True)
class ConnectionRule:
    rule_id: str
    award_units: int
    priority: int = 0
    left_groups_any: frozenset[str] = frozenset()
    right_groups_any: frozenset[str] = frozenset()
    left_element_ids: frozenset[str] = frozenset()
    right_element_ids: frozenset[str] = frozenset()
    require_adjacent: bool = True
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise DScoreError("connection rule_id is required")
        if self.award_units < 0:
            raise DScoreError("connection award cannot be negative")
        if not (
            self.left_groups_any
            or self.right_groups_any
            or self.left_element_ids
            or self.right_element_ids
        ):
            raise DScoreError("connection rule must constrain at least one side")


@dataclass(frozen=True)
class AdjustmentRule:
    rule_id: str
    value_units: int
    source_rule_id: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise DScoreError("adjustment rule_id is required")


@dataclass(frozen=True)
class DScorePolicy:
    rulepack_id: str
    rulepack_digest: str
    apparatus: Apparatus
    units_per_point: int
    elements: tuple[ElementRule, ...]
    counting: CountingPolicy
    composition: tuple[CompositionRequirement, ...] = ()
    connections: tuple[ConnectionRule, ...] = ()
    adjustments: tuple[AdjustmentRule, ...] = ()
    max_ambiguity_outcomes: int = 256

    def __post_init__(self) -> None:
        if not self.rulepack_id:
            raise DScoreError("rulepack_id is required")
        _require_sha256("rulepack_digest", self.rulepack_digest)
        if self.units_per_point < 1:
            raise DScoreError("units_per_point must be positive")
        if not self.elements:
            raise DScoreError("D-score policy must contain element rules")
        if self.max_ambiguity_outcomes < 1:
            raise DScoreError("max_ambiguity_outcomes must be positive")
        _require_unique("element IDs", (item.element_id for item in self.elements))
        _require_unique("composition requirement IDs", (item.requirement_id for item in self.composition))
        _require_unique("connection rule IDs", (item.rule_id for item in self.connections))
        _require_unique("adjustment rule IDs", (item.rule_id for item in self.adjustments))
        known_groups = {group for element in self.elements for group in element.groups}
        for quota in self.counting.quotas:
            if quota.group not in known_groups:
                raise DScoreError(f"counting quota references unknown group: {quota.group}")
        for requirement in self.composition:
            if requirement.match_group not in known_groups:
                raise DScoreError(
                    f"composition requirement references unknown group: {requirement.match_group}"
                )
        known_elements = {item.element_id for item in self.elements}
        for rule in self.connections:
            unknown = (rule.left_element_ids | rule.right_element_ids) - known_elements
            if unknown:
                raise DScoreError(
                    "connection rule references unknown element(s): " + ", ".join(sorted(unknown))
                )
            unknown_groups = (rule.left_groups_any | rule.right_groups_any) - known_groups
            if unknown_groups:
                raise DScoreError(
                    "connection rule references unknown group(s): "
                    + ", ".join(sorted(unknown_groups))
                )

    @property
    def element_map(self) -> Mapping[str, ElementRule]:
        return {item.element_id: item for item in self.elements}

    @property
    def adjustment_map(self) -> Mapping[str, AdjustmentRule]:
        return {item.rule_id: item for item in self.adjustments}

    @property
    def digest(self) -> str:
        return _stable_digest(_policy_payload(self))


@dataclass(frozen=True)
class AcceptedElementFact:
    fact_id: str
    sequence_index: int
    alternatives: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fact_id or self.sequence_index < 0 or not self.alternatives:
            raise DScoreError("element fact identity/order/alternatives are required")
        if len(set(self.alternatives)) != len(self.alternatives):
            raise DScoreError("element alternatives must be unique")
        if any(not item for item in self.alternatives):
            raise DScoreError("element alternatives cannot be empty")

    @property
    def normalized_alternatives(self) -> tuple[str, ...]:
        return tuple(sorted(self.alternatives))


@dataclass(frozen=True)
class AcceptedConnectionFact:
    connection_id: str
    left_fact_id: str
    right_fact_id: str
    continuous: bool
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.connection_id or not self.left_fact_id or not self.right_fact_id:
            raise DScoreError("connection identity and endpoint facts are required")
        if self.left_fact_id == self.right_fact_id:
            raise DScoreError("connection endpoints must be different facts")


@dataclass(frozen=True)
class AcceptedAdjustmentFact:
    adjustment_id: str
    rule_id: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.adjustment_id or not self.rule_id:
            raise DScoreError("adjustment identity and rule_id are required")


@dataclass(frozen=True)
class ElementLedgerEntry:
    fact_id: str
    sequence_index: int
    element_id: str
    value_units: int
    counted: bool
    reason: CountReason
    repetition_key: str
    groups: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class CompositionLedgerEntry:
    requirement_id: str
    status: CompositionStatus
    observed_count: int
    minimum_count: int
    award_units: int
    scope: str
    source_rule_id: str | None


@dataclass(frozen=True)
class ConnectionLedgerEntry:
    connection_id: str
    left_fact_id: str
    right_fact_id: str
    rule_id: str | None
    status: ConnectionStatus
    award_units: int
    evidence_ids: tuple[str, ...]
    source_rule_id: str | None = None


@dataclass(frozen=True)
class AdjustmentLedgerEntry:
    adjustment_id: str
    rule_id: str
    value_units: int
    evidence_ids: tuple[str, ...]
    source_rule_id: str | None


@dataclass(frozen=True)
class ResolvedDScoreOutcome:
    resolution: tuple[tuple[str, str], ...]
    elements: tuple[ElementLedgerEntry, ...]
    composition: tuple[CompositionLedgerEntry, ...]
    connections: tuple[ConnectionLedgerEntry, ...]
    adjustments: tuple[AdjustmentLedgerEntry, ...]
    element_total_units: int
    composition_total_units: int
    connection_total_units: int
    adjustment_total_units: int
    total_units: int
    warnings: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        return _stable_digest(_outcome_payload(self))


@dataclass(frozen=True)
class AlternativeImpact:
    element_id: str
    possible_total_units: tuple[int, ...]


@dataclass(frozen=True)
class AmbiguityRecord:
    fact_id: str
    alternatives: tuple[AlternativeImpact, ...]


@dataclass(frozen=True)
class DScoreLedger:
    rulepack_id: str
    rulepack_digest: str
    policy_digest: str
    apparatus: Apparatus
    units_per_point: int
    outcomes: tuple[ResolvedDScoreOutcome, ...]
    ambiguities: tuple[AmbiguityRecord, ...]
    possible_total_units: tuple[int, ...]
    evaluation_blockers: tuple[str, ...] = ()

    @property
    def score_resolved(self) -> bool:
        return not self.evaluation_blockers and len(self.possible_total_units) == 1

    @property
    def identity_resolved(self) -> bool:
        return not self.evaluation_blockers and not self.ambiguities

    @property
    def resolved_total_units(self) -> int | None:
        return self.possible_total_units[0] if self.score_resolved else None

    @property
    def resolved_score(self) -> str | None:
        if self.resolved_total_units is None:
            return None
        return format_score_units(self.resolved_total_units, self.units_per_point)

    def normalized_dict(self) -> dict:
        return {
            "schema": "ai.wagvid.dscore-ledger.v1",
            "rulepack_id": self.rulepack_id,
            "rulepack_digest": self.rulepack_digest,
            "policy_digest": self.policy_digest,
            "apparatus": self.apparatus.value,
            "units_per_point": self.units_per_point,
            "outcomes": [_outcome_payload(item) for item in self.outcomes],
            "ambiguities": [
                {
                    "fact_id": item.fact_id,
                    "alternatives": [
                        {
                            "element_id": impact.element_id,
                            "possible_total_units": list(impact.possible_total_units),
                        }
                        for impact in item.alternatives
                    ],
                }
                for item in self.ambiguities
            ],
            "possible_total_units": list(self.possible_total_units),
            "resolved_score": self.resolved_score,
            "evaluation_blockers": list(self.evaluation_blockers),
        }

    def normalized_json(self) -> str:
        return json.dumps(self.normalized_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalized_json().encode()).hexdigest()


class DeterministicDScoreEngine:
    def __init__(self, policy: DScorePolicy) -> None:
        self.policy = policy

    @property
    def rulepack_id(self) -> str:
        return self.policy.rulepack_id

    def evaluate(
        self,
        *,
        elements: Iterable[AcceptedElementFact],
        connections: Iterable[AcceptedConnectionFact] = (),
        adjustments: Iterable[AcceptedAdjustmentFact] = (),
    ) -> DScoreLedger:
        ordered = tuple(sorted(elements, key=lambda item: (item.sequence_index, item.fact_id)))
        if not ordered:
            raise DScoreError("D-score evaluation requires at least one accepted element fact")
        _require_unique("element fact IDs", (item.fact_id for item in ordered))
        _require_unique("element sequence indexes", (str(item.sequence_index) for item in ordered))
        connection_facts = tuple(sorted(connections, key=lambda item: item.connection_id))
        adjustment_facts = tuple(sorted(adjustments, key=lambda item: item.adjustment_id))
        _require_unique("connection IDs", (item.connection_id for item in connection_facts))
        _require_unique("adjustment IDs", (item.adjustment_id for item in adjustment_facts))

        element_map = self.policy.element_map
        for fact in ordered:
            unknown = set(fact.alternatives) - set(element_map)
            if unknown:
                raise DScoreError(
                    f"element fact {fact.fact_id} references unknown rulepack element(s): "
                    + ", ".join(sorted(unknown))
                )
        fact_ids = {item.fact_id for item in ordered}
        for connection in connection_facts:
            if connection.left_fact_id not in fact_ids or connection.right_fact_id not in fact_ids:
                raise DScoreError(
                    f"connection {connection.connection_id} references unknown element fact"
                )
        adjustment_map = self.policy.adjustment_map
        for adjustment in adjustment_facts:
            if adjustment.rule_id not in adjustment_map:
                raise DScoreError(
                    f"adjustment {adjustment.adjustment_id} references unknown rule: {adjustment.rule_id}"
                )

        ambiguity_count = prod(len(item.alternatives) for item in ordered)
        if ambiguity_count > self.policy.max_ambiguity_outcomes:
            return DScoreLedger(
                rulepack_id=self.policy.rulepack_id,
                rulepack_digest=self.policy.rulepack_digest,
                policy_digest=self.policy.digest,
                apparatus=self.policy.apparatus,
                units_per_point=self.policy.units_per_point,
                outcomes=(),
                ambiguities=tuple(
                    AmbiguityRecord(
                        fact_id=fact.fact_id,
                        alternatives=tuple(
                            AlternativeImpact(element_id=item, possible_total_units=())
                            for item in fact.normalized_alternatives
                        ),
                    )
                    for fact in ordered
                    if len(fact.alternatives) > 1
                ),
                possible_total_units=(),
                evaluation_blockers=(
                    f"ambiguity-outcome-limit-exceeded:{ambiguity_count}>{self.policy.max_ambiguity_outcomes}",
                ),
            )

        outcomes: list[ResolvedDScoreOutcome] = []
        alternatives = [fact.normalized_alternatives for fact in ordered]
        for selected in itertools.product(*alternatives):
            resolution = {fact.fact_id: element_id for fact, element_id in zip(ordered, selected)}
            outcomes.append(
                self._evaluate_resolution(
                    ordered,
                    resolution,
                    connection_facts,
                    adjustment_facts,
                )
            )
        outcomes.sort(key=lambda item: item.resolution)
        possible_totals = tuple(sorted({item.total_units for item in outcomes}))
        ambiguities = _build_ambiguity_records(ordered, outcomes)
        return DScoreLedger(
            rulepack_id=self.policy.rulepack_id,
            rulepack_digest=self.policy.rulepack_digest,
            policy_digest=self.policy.digest,
            apparatus=self.policy.apparatus,
            units_per_point=self.policy.units_per_point,
            outcomes=tuple(outcomes),
            ambiguities=ambiguities,
            possible_total_units=possible_totals,
        )

    def _evaluate_resolution(
        self,
        facts: tuple[AcceptedElementFact, ...],
        resolution: Mapping[str, str],
        connection_facts: tuple[AcceptedConnectionFact, ...],
        adjustment_facts: tuple[AcceptedAdjustmentFact, ...],
    ) -> ResolvedDScoreOutcome:
        rules = self.policy.element_map
        resolved_rules = tuple(rules[resolution[fact.fact_id]] for fact in facts)
        counted_indexes, warnings = _select_counted_indexes(
            facts,
            resolved_rules,
            self.policy.counting,
        )
        repetition_eligible = _repetition_eligible_indexes(
            resolved_rules,
            self.policy.counting.repetition_limit_per_key,
        )
        entries = []
        quota_counts = _quota_counts(counted_indexes, resolved_rules, self.policy.counting.quotas)
        for index, (fact, rule) in enumerate(zip(facts, resolved_rules)):
            if index in counted_indexes:
                reason = CountReason.COUNTED
            elif index not in repetition_eligible:
                reason = CountReason.REPETITION
            elif _would_exceed_quota(
                index,
                resolved_rules,
                quota_counts,
                self.policy.counting.quotas,
            ):
                reason = CountReason.GROUP_QUOTA
            elif (
                self.policy.counting.max_counted_elements is not None
                and len(counted_indexes) >= self.policy.counting.max_counted_elements
            ):
                reason = CountReason.COUNT_LIMIT
            else:
                reason = CountReason.LOWER_VALUE_SELECTION
            entries.append(
                ElementLedgerEntry(
                    fact_id=fact.fact_id,
                    sequence_index=fact.sequence_index,
                    element_id=rule.element_id,
                    value_units=rule.value_units,
                    counted=index in counted_indexes,
                    reason=reason,
                    repetition_key=rule.repetition_key,
                    groups=tuple(sorted(rule.groups)),
                    evidence_ids=tuple(fact.evidence_ids),
                )
            )

        composition = _evaluate_composition(
            self.policy.composition,
            resolved_rules,
            counted_indexes,
        )
        connection_entries = _evaluate_connections(
            self.policy.connections,
            facts,
            resolved_rules,
            connection_facts,
        )
        adjustment_entries = tuple(
            AdjustmentLedgerEntry(
                adjustment_id=fact.adjustment_id,
                rule_id=fact.rule_id,
                value_units=self.policy.adjustment_map[fact.rule_id].value_units,
                evidence_ids=tuple(fact.evidence_ids),
                source_rule_id=self.policy.adjustment_map[fact.rule_id].source_rule_id,
            )
            for fact in adjustment_facts
        )
        element_total = sum(resolved_rules[index].value_units for index in counted_indexes)
        composition_total = sum(item.award_units for item in composition)
        connection_total = sum(item.award_units for item in connection_entries)
        adjustment_total = sum(item.value_units for item in adjustment_entries)
        return ResolvedDScoreOutcome(
            resolution=tuple((fact.fact_id, resolution[fact.fact_id]) for fact in facts),
            elements=tuple(entries),
            composition=composition,
            connections=connection_entries,
            adjustments=adjustment_entries,
            element_total_units=element_total,
            composition_total_units=composition_total,
            connection_total_units=connection_total,
            adjustment_total_units=adjustment_total,
            total_units=element_total + composition_total + connection_total + adjustment_total,
            warnings=warnings,
        )


def format_score_units(units: int, units_per_point: int) -> str:
    if units_per_point < 1:
        raise DScoreError("units_per_point must be positive")
    value = Decimal(units) / Decimal(units_per_point)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _repetition_eligible_indexes(
    rules: tuple[ElementRule, ...],
    limit: int,
) -> frozenset[int]:
    seen: dict[str, int] = {}
    eligible = set()
    for index, rule in enumerate(rules):
        count = seen.get(rule.repetition_key, 0)
        if count < limit:
            eligible.add(index)
        seen[rule.repetition_key] = count + 1
    return frozenset(eligible)


def _select_counted_indexes(
    facts: tuple[AcceptedElementFact, ...],
    rules: tuple[ElementRule, ...],
    policy: CountingPolicy,
) -> tuple[frozenset[int], tuple[str, ...]]:
    eligible = _repetition_eligible_indexes(rules, policy.repetition_limit_per_key)
    maximum = policy.max_counted_elements
    if maximum is None:
        maximum = len(eligible)
    maximum = min(maximum, len(eligible))

    # DP state: (selected_count, quota_counts) -> (score_units, selected_indices)
    initial_counts = tuple(0 for _ in policy.quotas)
    states: dict[tuple[int, tuple[int, ...]], tuple[int, tuple[int, ...]]] = {
        (0, initial_counts): (0, ())
    }
    for index in sorted(eligible):
        rule = rules[index]
        next_states = dict(states)
        for (selected_count, quota_counts), (score, selected) in states.items():
            if selected_count >= maximum:
                continue
            updated_counts = list(quota_counts)
            blocked = False
            for quota_index, quota in enumerate(policy.quotas):
                if quota.group in rule.groups:
                    updated_counts[quota_index] += 1
                    if (
                        quota.maximum_counted is not None
                        and updated_counts[quota_index] > quota.maximum_counted
                    ):
                        blocked = True
                        break
            if blocked:
                continue
            new_key = (selected_count + 1, tuple(updated_counts))
            new_value = (score + rule.value_units, selected + (index,))
            prior = next_states.get(new_key)
            if prior is None or _selection_is_better(new_value, prior):
                next_states[new_key] = new_value
        states = next_states

    satisfying = [
        (key, value)
        for key, value in states.items()
        if all(
            key[1][quota_index] >= quota.minimum_counted
            for quota_index, quota in enumerate(policy.quotas)
        )
    ]
    candidates = satisfying or list(states.items())
    best = max(
        candidates,
        key=lambda item: (
            item[1][0],
            item[0][0],
            tuple(-index for index in item[1][1]),
        ),
    )
    selected = frozenset(best[1][1])
    warnings = []
    counts = best[0][1]
    for quota_index, quota in enumerate(policy.quotas):
        if counts[quota_index] < quota.minimum_counted:
            warnings.append(
                f"counting-quota-minimum-unmet:{quota.group}:{counts[quota_index]}<{quota.minimum_counted}"
            )
    return selected, tuple(warnings)


def _selection_is_better(
    candidate: tuple[int, tuple[int, ...]],
    prior: tuple[int, tuple[int, ...]],
) -> bool:
    if candidate[0] != prior[0]:
        return candidate[0] > prior[0]
    return candidate[1] < prior[1]


def _quota_counts(
    selected: frozenset[int],
    rules: tuple[ElementRule, ...],
    quotas: tuple[CountingQuota, ...],
) -> tuple[int, ...]:
    return tuple(
        sum(1 for index in selected if quota.group in rules[index].groups)
        for quota in quotas
    )


def _would_exceed_quota(
    index: int,
    rules: tuple[ElementRule, ...],
    selected_quota_counts: tuple[int, ...],
    quotas: tuple[CountingQuota, ...],
) -> bool:
    rule = rules[index]
    return any(
        quota.maximum_counted is not None
        and quota.group in rule.groups
        and selected_quota_counts[quota_index] >= quota.maximum_counted
        for quota_index, quota in enumerate(quotas)
    )


def _evaluate_composition(
    requirements: tuple[CompositionRequirement, ...],
    rules: tuple[ElementRule, ...],
    counted: frozenset[int],
) -> tuple[CompositionLedgerEntry, ...]:
    entries = []
    for requirement in requirements:
        indexes = range(len(rules)) if requirement.scope == "performed" else sorted(counted)
        observed = sum(1 for index in indexes if requirement.match_group in rules[index].groups)
        satisfied = observed >= requirement.minimum_count
        entries.append(
            CompositionLedgerEntry(
                requirement_id=requirement.requirement_id,
                status=(CompositionStatus.SATISFIED if satisfied else CompositionStatus.UNSATISFIED),
                observed_count=observed,
                minimum_count=requirement.minimum_count,
                award_units=requirement.award_units if satisfied else 0,
                scope=requirement.scope,
                source_rule_id=requirement.source_rule_id,
            )
        )
    return tuple(entries)


def _evaluate_connections(
    rules: tuple[ConnectionRule, ...],
    facts: tuple[AcceptedElementFact, ...],
    element_rules: tuple[ElementRule, ...],
    connections: tuple[AcceptedConnectionFact, ...],
) -> tuple[ConnectionLedgerEntry, ...]:
    fact_index = {fact.fact_id: index for index, fact in enumerate(facts)}
    entries = []
    for connection in connections:
        left_index = fact_index[connection.left_fact_id]
        right_index = fact_index[connection.right_fact_id]
        left = element_rules[left_index]
        right = element_rules[right_index]
        if not connection.continuous:
            entries.append(
                ConnectionLedgerEntry(
                    connection_id=connection.connection_id,
                    left_fact_id=connection.left_fact_id,
                    right_fact_id=connection.right_fact_id,
                    rule_id=None,
                    status=ConnectionStatus.INTERRUPTED,
                    award_units=0,
                    evidence_ids=tuple(connection.evidence_ids),
                )
            )
            continue
        matching = [
            rule for rule in rules
            if _connection_rule_matches(rule, left, right, left_index, right_index)
        ]
        if not matching:
            status = (
                ConnectionStatus.NOT_ADJACENT
                if any(rule.require_adjacent for rule in rules) and right_index != left_index + 1
                else ConnectionStatus.NO_MATCHING_RULE
            )
            entries.append(
                ConnectionLedgerEntry(
                    connection_id=connection.connection_id,
                    left_fact_id=connection.left_fact_id,
                    right_fact_id=connection.right_fact_id,
                    rule_id=None,
                    status=status,
                    award_units=0,
                    evidence_ids=tuple(connection.evidence_ids),
                )
            )
            continue
        highest_priority = max(item.priority for item in matching)
        selected = [item for item in matching if item.priority == highest_priority]
        if len(selected) != 1:
            raise DScoreError(
                f"connection {connection.connection_id} matches multiple equal-priority rules: "
                + ", ".join(sorted(item.rule_id for item in selected))
            )
        rule = selected[0]
        entries.append(
            ConnectionLedgerEntry(
                connection_id=connection.connection_id,
                left_fact_id=connection.left_fact_id,
                right_fact_id=connection.right_fact_id,
                rule_id=rule.rule_id,
                status=ConnectionStatus.AWARDED,
                award_units=rule.award_units,
                evidence_ids=tuple(connection.evidence_ids),
                source_rule_id=rule.source_rule_id,
            )
        )
    return tuple(entries)


def _connection_rule_matches(
    rule: ConnectionRule,
    left: ElementRule,
    right: ElementRule,
    left_index: int,
    right_index: int,
) -> bool:
    if rule.require_adjacent and right_index != left_index + 1:
        return False
    if rule.left_element_ids and left.element_id not in rule.left_element_ids:
        return False
    if rule.right_element_ids and right.element_id not in rule.right_element_ids:
        return False
    if rule.left_groups_any and not (left.groups & rule.left_groups_any):
        return False
    return not rule.right_groups_any or bool(right.groups & rule.right_groups_any)


def _build_ambiguity_records(
    facts: tuple[AcceptedElementFact, ...],
    outcomes: list[ResolvedDScoreOutcome],
) -> tuple[AmbiguityRecord, ...]:
    records = []
    for fact in facts:
        if len(fact.alternatives) <= 1:
            continue
        impacts = []
        for element_id in fact.normalized_alternatives:
            totals = {
                outcome.total_units
                for outcome in outcomes
                if dict(outcome.resolution)[fact.fact_id] == element_id
            }
            impacts.append(
                AlternativeImpact(element_id=element_id, possible_total_units=tuple(sorted(totals)))
            )
        records.append(AmbiguityRecord(fact_id=fact.fact_id, alternatives=tuple(impacts)))
    return tuple(records)


def _policy_payload(policy: DScorePolicy) -> dict:
    return {
        "rulepack_id": policy.rulepack_id,
        "rulepack_digest": policy.rulepack_digest,
        "apparatus": policy.apparatus.value,
        "units_per_point": policy.units_per_point,
        "elements": [
            {
                **asdict(item),
                "groups": sorted(item.groups),
            }
            for item in sorted(policy.elements, key=lambda value: value.element_id)
        ],
        "counting": {
            "max_counted_elements": policy.counting.max_counted_elements,
            "repetition_limit_per_key": policy.counting.repetition_limit_per_key,
            "quotas": [asdict(item) for item in sorted(policy.counting.quotas, key=lambda value: value.group)],
        },
        "composition": [asdict(item) for item in sorted(policy.composition, key=lambda value: value.requirement_id)],
        "connections": [
            {
                **asdict(item),
                "left_groups_any": sorted(item.left_groups_any),
                "right_groups_any": sorted(item.right_groups_any),
                "left_element_ids": sorted(item.left_element_ids),
                "right_element_ids": sorted(item.right_element_ids),
            }
            for item in sorted(policy.connections, key=lambda value: value.rule_id)
        ],
        "adjustments": [asdict(item) for item in sorted(policy.adjustments, key=lambda value: value.rule_id)],
        "max_ambiguity_outcomes": policy.max_ambiguity_outcomes,
    }


def _outcome_payload(outcome: ResolvedDScoreOutcome) -> dict:
    return {
        "resolution": [list(item) for item in outcome.resolution],
        "elements": [
            {
                **asdict(item),
                "reason": item.reason.value,
                "groups": list(item.groups),
                "evidence_ids": list(item.evidence_ids),
            }
            for item in outcome.elements
        ],
        "composition": [
            {
                **asdict(item),
                "status": item.status.value,
            }
            for item in outcome.composition
        ],
        "connections": [
            {
                **asdict(item),
                "status": item.status.value,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in outcome.connections
        ],
        "adjustments": [
            {
                **asdict(item),
                "evidence_ids": list(item.evidence_ids),
            }
            for item in outcome.adjustments
        ],
        "element_total_units": outcome.element_total_units,
        "composition_total_units": outcome.composition_total_units,
        "connection_total_units": outcome.connection_total_units,
        "adjustment_total_units": outcome.adjustment_total_units,
        "total_units": outcome.total_units,
        "warnings": list(outcome.warnings),
    }


def _stable_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DScoreError(f"{label} must be lowercase SHA-256 hexadecimal")


def _require_unique(label: str, values: Iterable[str]) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise DScoreError(f"{label} must be unique")
