import json

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.dscore import (
    AcceptedAdjustmentFact,
    AcceptedConnectionFact,
    AcceptedElementFact,
    AdjustmentRule,
    CompositionRequirement,
    CompositionStatus,
    ConnectionRule,
    ConnectionStatus,
    CountReason,
    CountingPolicy,
    CountingQuota,
    DScoreError,
    DScorePolicy,
    DeterministicDScoreEngine,
    ElementRule,
    format_score_units,
)


RULEPACK_DIGEST = "a" * 64


def policy(*, digest: str = RULEPACK_DIGEST, max_outcomes: int = 256) -> DScorePolicy:
    # Synthetic values only. These are engine fixtures, not FIG scoring content.
    return DScorePolicy(
        rulepack_id="fixture-rulepack@v1",
        rulepack_digest=digest,
        apparatus=Apparatus.BB,
        units_per_point=10,
        elements=(
            ElementRule("A", 1, "rep-A", frozenset({"acro", "low"}), "fixture.element.A"),
            ElementRule("B", 3, "rep-B", frozenset({"dance", "medium"}), "fixture.element.B"),
            ElementRule("B-alt", 3, "rep-B-alt", frozenset({"dance", "medium"}), "fixture.element.B-alt"),
            ElementRule("C", 2, "rep-C", frozenset({"acro", "medium"}), "fixture.element.C"),
            ElementRule("D", 4, "rep-D", frozenset({"acro", "high"}), "fixture.element.D"),
            ElementRule("E", 5, "rep-E", frozenset({"dance", "high"}), "fixture.element.E"),
        ),
        counting=CountingPolicy(
            max_counted_elements=3,
            repetition_limit_per_key=1,
            quotas=(
                CountingQuota("acro", minimum_counted=1, maximum_counted=2),
                CountingQuota("dance", minimum_counted=1, maximum_counted=2),
            ),
        ),
        composition=(
            CompositionRequirement(
                "fixture.cr.dance",
                "dance",
                minimum_count=1,
                award_units=5,
                scope="performed",
                source_rule_id="fixture.cr.source",
            ),
        ),
        connections=(
            ConnectionRule(
                "fixture.connection.acro-dance",
                award_units=2,
                priority=10,
                left_groups_any=frozenset({"acro"}),
                right_groups_any=frozenset({"dance"}),
                require_adjacent=True,
                source_rule_id="fixture.connection.source",
            ),
        ),
        adjustments=(
            AdjustmentRule("fixture.adjustment", -1, "fixture.adjustment.source"),
        ),
        max_ambiguity_outcomes=max_outcomes,
    )


def fact(fact_id: str, sequence: int, *alternatives: str) -> AcceptedElementFact:
    return AcceptedElementFact(
        fact_id=fact_id,
        sequence_index=sequence,
        alternatives=alternatives,
        evidence_ids=(f"ev-{fact_id}",),
    )


def test_counting_selects_highest_value_valid_subset_under_group_quotas():
    ledger = DeterministicDScoreEngine(policy()).evaluate(
        elements=(
            fact("f0", 0, "A"),
            fact("f1", 1, "C"),
            fact("f2", 2, "D"),
            fact("f3", 3, "B"),
        )
    )
    outcome = ledger.outcomes[0]
    by_fact = {entry.fact_id: entry for entry in outcome.elements}

    assert by_fact["f2"].counted is True
    assert by_fact["f1"].counted is True
    assert by_fact["f3"].counted is True
    assert by_fact["f0"].counted is False
    assert by_fact["f0"].reason in {CountReason.COUNT_LIMIT, CountReason.GROUP_QUOTA}
    assert outcome.element_total_units == 9
    assert outcome.composition_total_units == 5
    assert outcome.total_units == 14
    assert ledger.resolved_score == "1.4"


def test_repeated_element_is_explicitly_non_counted_before_value_selection():
    repeated_policy = DScorePolicy(
        **{
            **policy().__dict__,
            "elements": (
                ElementRule("A1", 4, "same-skill", frozenset({"acro"})),
                ElementRule("A2", 4, "same-skill", frozenset({"acro"})),
                ElementRule("B", 3, "other", frozenset({"dance"})),
            ),
            "counting": CountingPolicy(max_counted_elements=3, repetition_limit_per_key=1),
            "composition": (),
            "connections": (),
            "adjustments": (),
        }
    )
    ledger = DeterministicDScoreEngine(repeated_policy).evaluate(
        elements=(fact("first", 0, "A1"), fact("repeat", 1, "A2"), fact("other", 2, "B"))
    )
    entries = {item.fact_id: item for item in ledger.outcomes[0].elements}
    assert entries["first"].counted is True
    assert entries["repeat"].counted is False
    assert entries["repeat"].reason is CountReason.REPETITION
    assert entries["other"].counted is True


def test_composition_requirement_is_a_separate_auditable_ledger_channel():
    engine = DeterministicDScoreEngine(policy())
    satisfied = engine.evaluate(elements=(fact("a", 0, "A"), fact("b", 1, "B"))).outcomes[0]
    unsatisfied = engine.evaluate(elements=(fact("a", 0, "A"), fact("c", 1, "C"))).outcomes[0]

    assert satisfied.composition[0].status is CompositionStatus.SATISFIED
    assert satisfied.composition[0].award_units == 5
    assert unsatisfied.composition[0].status is CompositionStatus.UNSATISFIED
    assert unsatisfied.composition[0].award_units == 0


def test_connection_requires_accepted_continuity_and_rule_match():
    elements = (fact("acro", 0, "D"), fact("dance", 1, "B"))
    engine = DeterministicDScoreEngine(policy())
    awarded = engine.evaluate(
        elements=elements,
        connections=(
            AcceptedConnectionFact("cx", "acro", "dance", True, ("ev-cx",)),
        ),
    ).outcomes[0]
    interrupted = engine.evaluate(
        elements=elements,
        connections=(
            AcceptedConnectionFact("cx", "acro", "dance", False, ("ev-cx",)),
        ),
    ).outcomes[0]

    assert awarded.connections[0].status is ConnectionStatus.AWARDED
    assert awarded.connections[0].award_units == 2
    assert interrupted.connections[0].status is ConnectionStatus.INTERRUPTED
    assert interrupted.connections[0].award_units == 0


def test_non_adjacent_connection_does_not_receive_adjacent_rule_award():
    ledger = DeterministicDScoreEngine(policy()).evaluate(
        elements=(fact("left", 0, "D"), fact("middle", 1, "A"), fact("right", 2, "B")),
        connections=(AcceptedConnectionFact("cx", "left", "right", True),),
    )
    assert ledger.outcomes[0].connections[0].status is ConnectionStatus.NOT_ADJACENT
    assert ledger.outcomes[0].connections[0].award_units == 0


def test_explicit_adjustment_uses_rulepack_value_not_caller_supplied_arithmetic():
    ledger = DeterministicDScoreEngine(policy()).evaluate(
        elements=(fact("a", 0, "A"), fact("b", 1, "B")),
        adjustments=(AcceptedAdjustmentFact("adj-1", "fixture.adjustment", ("ev-adj",)),),
    )
    outcome = ledger.outcomes[0]
    assert outcome.adjustments[0].value_units == -1
    assert outcome.adjustment_total_units == -1
    assert outcome.total_units == outcome.element_total_units + outcome.composition_total_units - 1


def test_equal_value_identity_ambiguity_can_leave_score_resolved():
    ledger = DeterministicDScoreEngine(policy()).evaluate(
        elements=(fact("a", 0, "A"), fact("amb", 1, "B", "B-alt"))
    )
    assert len(ledger.outcomes) == 2
    assert ledger.identity_resolved is False
    assert ledger.score_resolved is True
    assert ledger.possible_total_units == (9,)
    assert ledger.ambiguities[0].fact_id == "amb"
    assert {item.element_id for item in ledger.ambiguities[0].alternatives} == {"B", "B-alt"}


def test_different_value_ambiguity_propagates_possible_totals_instead_of_guessing():
    ledger = DeterministicDScoreEngine(policy()).evaluate(
        elements=(fact("a", 0, "A"), fact("amb", 1, "B", "E"))
    )
    assert ledger.score_resolved is False
    assert ledger.resolved_score is None
    assert ledger.possible_total_units == (9, 11)
    impacts = {item.element_id: item.possible_total_units for item in ledger.ambiguities[0].alternatives}
    assert impacts == {"B": (9,), "E": (11,)}


def test_ambiguity_bound_fails_closed_without_enumerating_unbounded_combinations():
    engine = DeterministicDScoreEngine(policy(max_outcomes=3))
    ledger = engine.evaluate(
        elements=(fact("a", 0, "A", "C"), fact("b", 1, "B", "E"))
    )
    assert ledger.outcomes == ()
    assert ledger.possible_total_units == ()
    assert ledger.score_resolved is False
    assert ledger.evaluation_blockers == ("ambiguity-outcome-limit-exceeded:4>3",)


def test_normalized_ledger_is_byte_stable_and_input_order_independent():
    engine = DeterministicDScoreEngine(policy())
    elements = (
        fact("f0", 0, "A"),
        fact("f1", 1, "D"),
        fact("f2", 2, "B"),
    )
    connection = AcceptedConnectionFact("cx", "f1", "f2", True, ("ev-cx",))
    adjustment = AcceptedAdjustmentFact("adj", "fixture.adjustment", ("ev-adj",))
    first = engine.evaluate(
        elements=elements,
        connections=(connection,),
        adjustments=(adjustment,),
    )
    second = engine.evaluate(
        elements=tuple(reversed(elements)),
        connections=(connection,),
        adjustments=(adjustment,),
    )

    assert first.normalized_json() == second.normalized_json()
    assert first.digest == second.digest
    parsed = json.loads(first.normalized_json())
    assert parsed["schema"] == "ai.wagvid.dscore-ledger.v1"
    assert parsed["rulepack_digest"] == RULEPACK_DIGEST


def test_rulepack_or_policy_change_changes_ledger_provenance_digest():
    elements = (fact("a", 0, "A"), fact("b", 1, "B"))
    first = DeterministicDScoreEngine(policy(digest="a" * 64)).evaluate(elements=elements)
    second = DeterministicDScoreEngine(policy(digest="b" * 64)).evaluate(elements=elements)
    assert first.possible_total_units == second.possible_total_units
    assert first.policy_digest != second.policy_digest
    assert first.digest != second.digest


def test_counting_quota_minimum_shortfall_is_visible_not_hidden():
    no_dance = DeterministicDScoreEngine(policy()).evaluate(
        elements=(fact("a", 0, "A"), fact("c", 1, "C"), fact("d", 2, "D"))
    ).outcomes[0]
    assert no_dance.warnings == ("counting-quota-minimum-unmet:dance:0<1",)


def test_equal_priority_overlapping_connection_rules_are_rejected_as_rulepack_ambiguity():
    base = policy()
    conflicting = DScorePolicy(
        **{
            **base.__dict__,
            "connections": (
                base.connections[0],
                ConnectionRule(
                    "fixture.connection.conflict",
                    award_units=3,
                    priority=10,
                    left_groups_any=frozenset({"acro"}),
                    right_groups_any=frozenset({"dance"}),
                ),
            ),
        }
    )
    with pytest.raises(DScoreError, match="multiple equal-priority rules"):
        DeterministicDScoreEngine(conflicting).evaluate(
            elements=(fact("a", 0, "D"), fact("b", 1, "B")),
            connections=(AcceptedConnectionFact("cx", "a", "b", True),),
        )


def test_score_formatting_uses_exact_integer_units_without_binary_float_artifacts():
    assert format_score_units(53, 10) == "5.3"
    assert format_score_units(125, 100) == "1.25"
    assert format_score_units(-1, 10) == "-0.1"
