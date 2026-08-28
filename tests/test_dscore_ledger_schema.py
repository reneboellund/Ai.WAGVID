from pathlib import Path

from jsonschema import Draft202012Validator

from ai_wagvid.domain import Apparatus
from ai_wagvid.dscore import (
    AcceptedConnectionFact,
    AcceptedElementFact,
    CompositionRequirement,
    ConnectionRule,
    CountingPolicy,
    DeterministicDScoreEngine,
    DScorePolicy,
    ElementRule,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
SCHEMA = load_schema(ROOT / "schemas" / "dscore-ledger-v1.schema.json")


def engine() -> DeterministicDScoreEngine:
    return DeterministicDScoreEngine(
        DScorePolicy(
            rulepack_id="fixture@v1",
            rulepack_digest="a" * 64,
            apparatus=Apparatus.FX,
            units_per_point=10,
            elements=(
                ElementRule("a", 1, "rep-a", frozenset({"acro"}), "fixture.a"),
                ElementRule("b", 2, "rep-b", frozenset({"dance"}), "fixture.b"),
            ),
            counting=CountingPolicy(max_counted_elements=2),
            composition=(
                CompositionRequirement("cr", "dance", 1, 5, "performed", "fixture.cr"),
            ),
            connections=(
                ConnectionRule(
                    "cx-rule",
                    2,
                    left_groups_any=frozenset({"acro"}),
                    right_groups_any=frozenset({"dance"}),
                    source_rule_id="fixture.cx",
                ),
            ),
        )
    )


def test_resolved_ledger_validates_against_public_schema():
    ledger = engine().evaluate(
        elements=(
            AcceptedElementFact("f0", 0, ("a",), ("ev-a",)),
            AcceptedElementFact("f1", 1, ("b",), ("ev-b",)),
        ),
        connections=(AcceptedConnectionFact("cx", "f0", "f1", True, ("ev-cx",)),),
    )
    errors = list(Draft202012Validator(SCHEMA).iter_errors(ledger.normalized_dict()))
    assert errors == []


def test_ambiguous_ledger_validates_against_public_schema():
    ledger = engine().evaluate(
        elements=(
            AcceptedElementFact("f0", 0, ("a",)),
            AcceptedElementFact("f1", 1, ("a", "b")),
        )
    )
    errors = list(Draft202012Validator(SCHEMA).iter_errors(ledger.normalized_dict()))
    assert errors == []
    assert ledger.ambiguities


def test_fail_closed_ambiguity_limit_ledger_validates_against_public_schema():
    base = engine().policy
    limited = DeterministicDScoreEngine(
        DScorePolicy(**{**base.__dict__, "max_ambiguity_outcomes": 1})
    ).evaluate(
        elements=(AcceptedElementFact("f0", 0, ("a", "b")),)
    )
    errors = list(Draft202012Validator(SCHEMA).iter_errors(limited.normalized_dict()))
    assert errors == []
    assert limited.evaluation_blockers
