from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_wagvid.deduction_policy import deduction_policy_from_mapping
from ai_wagvid.deductions import (
    DecisionAction,
    DeductionCandidate,
    DeductionDecision,
    DeductionDecisionLedger,
    DeductionError,
    build_deduction_ledger,
    evaluate_deduction_candidate,
)
from wagvid_rules.validation import load_schema

ROOT = Path(__file__).parents[1]
POLICY_SCHEMA = load_schema(ROOT / "schemas" / "deduction-policy-v1.schema.json")
LEDGER_SCHEMA = load_schema(ROOT / "schemas" / "deduction-ledger-v1.schema.json")


def payload() -> dict:
    return {
        "schema": "ai.wagvid.deduction-policy.v1",
        "rulepack_id": "fixture@v1",
        "rulepack_digest": "a" * 64,
        "apparatus": "BB",
        "units_per_point": 10,
        "rules": [
            {
                "rule_id": "fixture.execution",
                "channel": "execution",
                "criterion_id": "shape",
                "scope": "element",
                "severities": [
                    {"severity_id": "small", "deduction_units": 1, "source_rule_id": "fixture.small"},
                    {"severity_id": "medium", "deduction_units": 3, "source_rule_id": "fixture.medium"},
                ],
                "required_camera_capabilities": ["body-visible"],
                "minimum_evidence_quality_milli": 700,
                "minimum_model_confidence_milli": 800,
                "source_rule_id": "fixture.execution.source",
            },
            {
                "rule_id": "fixture.artistry",
                "channel": "artistry",
                "criterion_id": "criterion-evidence",
                "scope": "routine",
                "severities": [{"severity_id": "criterion-loss", "deduction_units": 2}],
                "human_judgement_required": True,
                "source_rule_id": "fixture.artistry.source",
            },
        ],
    }


def candidate() -> DeductionCandidate:
    return DeductionCandidate(
        candidate_id="cand-1",
        rule_id="fixture.execution",
        scope_ref="element-1",
        evidence_ids=("ev-1",),
        observation_ids=("obs-1",),
        proposed_severity_id="small",
        model_confidence_milli=900,
        evidence_quality_milli=900,
        camera_ids=("cam-a",),
        camera_capabilities=frozenset({"body-visible"}),
        producer_id="fixture-model",
        producer_digest="b" * 64,
    )


def test_policy_fixture_is_schema_valid_and_loadable():
    value = payload()
    assert list(Draft202012Validator(POLICY_SCHEMA).iter_errors(value)) == []
    parsed = deduction_policy_from_mapping(value)
    assert parsed.rules[0].criterion_id == "shape"
    assert parsed.rules[1].human_judgement_required is True
    assert len(parsed.digest) == 64


def test_schema_and_loader_both_reject_machine_final_artistry():
    value = payload()
    value["rules"][1]["human_judgement_required"] = False
    assert list(Draft202012Validator(POLICY_SCHEMA).iter_errors(value))
    with pytest.raises(DeductionError, match="artistry criteria must require human judgement"):
        deduction_policy_from_mapping(value)


def test_unknown_executable_policy_fields_are_rejected():
    value = payload()
    value["rules"][0]["python_expression"] = "return official_score"
    assert list(Draft202012Validator(POLICY_SCHEMA).iter_errors(value))
    with pytest.raises(DeductionError, match="unknown field"):
        deduction_policy_from_mapping(value)


def test_human_adjudicated_ledger_validates_against_public_schema():
    policy = deduction_policy_from_mapping(payload())
    proposal = evaluate_deduction_candidate(policy, candidate())
    decisions = DeductionDecisionLedger(policy, (proposal,))
    decisions.append(
        DeductionDecision(
            decision_id="decision-1",
            proposal_digest=proposal.digest,
            candidate_id=proposal.candidate_id,
            action=DecisionAction.ACCEPT,
            author_id="reviewer-a",
            created_at=__import__("datetime").datetime(2026, 8, 17, 12, 0, tzinfo=__import__("datetime").UTC),
            reason="Reviewed source evidence",
            selected_severity_id="small",
        )
    )
    ledger = build_deduction_ledger(policy, (proposal,), decisions)
    assert list(Draft202012Validator(LEDGER_SCHEMA).iter_errors(ledger.normalized_dict())) == []
    assert ledger.accepted_deduction_units == 1


def test_unresolved_ledger_is_valid_output_not_a_fake_zero_deduction_conclusion():
    policy = deduction_policy_from_mapping(payload())
    proposal = evaluate_deduction_candidate(policy, candidate())
    decisions = DeductionDecisionLedger(policy, (proposal,))
    ledger = build_deduction_ledger(policy, (proposal,), decisions)
    assert list(Draft202012Validator(LEDGER_SCHEMA).iter_errors(ledger.normalized_dict())) == []
    assert ledger.accepted_deduction_units == 0
    assert ledger.fully_resolved is False
    assert ledger.unresolved_candidate_ids == ("cand-1",)
