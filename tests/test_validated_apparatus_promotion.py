from datetime import UTC, datetime

from ai_wagvid.apparatus_promotion import (
    ApparatusAcceptedFacts,
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    ApparatusRulepackBinding,
    BenchmarkMetric,
    BenchmarkRunState,
    BenchmarkSliceResult,
    PromotionStatus,
    SliceStatus,
    evaluate_accepted_dscore,
)
from ai_wagvid.domain import Apparatus
from ai_wagvid.dscore import AcceptedElementFact, CountingPolicy, DScorePolicy, ElementRule
from ai_wagvid.rulepack_promotion import RulepackReadiness
from ai_wagvid.validated_apparatus_promotion import evaluate_validated_apparatus_promotion

T0 = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def fixtures():
    model = ApparatusModelBundle(
        model_bundle_id="fixture-model", apparatus=Apparatus.VT,
        adapter_id="adapter", adapter_version="1",
        checkpoint_sha256="1"*64, config_sha256="2"*64, label_map_sha256="3"*64,
        training_dataset_manifest_sha256="4"*64, training_rights_ref="rights",
        framework="framework", framework_version="1", created_at=T0,
    )
    policy = DScorePolicy(
        rulepack_id="rulepack-fixture", rulepack_digest="5"*64, apparatus=Apparatus.VT,
        units_per_point=10,
        elements=(ElementRule("VT.a", 40, "a", frozenset({"family-a"})),),
        counting=CountingPolicy(max_counted_elements=1),
    )
    binding = ApparatusRulepackBinding.from_policy(
        policy, reviewed_by="reviewer", reviewer_qualification_ref="qualified-wag", reviewed_at=T0
    )
    facts = ApparatusAcceptedFacts(
        apparatus=Apparatus.VT, model_bundle_digest=model.digest,
        evidence_bundle_digest="6"*64, review_decision_digest="7"*64,
        elements=(AcceptedElementFact("f1", 0, ("VT.a",), ("e1",)),),
    )
    ledger = evaluate_accepted_dscore(policy=policy, binding=binding, accepted_facts=facts)
    benchmark = ApparatusBenchmarkReport(
        benchmark_id="bench", apparatus=Apparatus.VT, run_state=BenchmarkRunState.EXECUTED,
        model_bundle_digest=model.digest, rulepack_digest=binding.rulepack_digest,
        benchmark_manifest_sha256="8"*64, validation_dataset_manifest_sha256="9"*64,
        split_manifest_sha256="a"*64, rights_ref="validation-rights",
        hardware_runtime_manifest_sha256="b"*64,
        slices=(BenchmarkSliceResult(
            slice_id="required", dimensions=(("camera","side"),),
            metrics=(BenchmarkMetric("top1", 950, 900, True),),
            status=SliceStatus.PASS, sample_count=20,
        ),),
        required_slice_ids=("required",), executed_at=T0,
    )
    return model, binding, facts, ledger, benchmark


def test_unreviewed_rulepack_blocks_otherwise_passing_promotion():
    model, binding, facts, ledger, benchmark = fixtures()
    readiness = RulepackReadiness(
        rulepack_id=binding.rulepack_id,
        ready=False,
        blockers=("rulepack-manifest-not-approved",),
        manifest_sha256=None,
        source_ids=("wag-source",),
    )
    decision = evaluate_validated_apparatus_promotion(
        model=model, binding=binding, accepted_facts=facts,
        benchmark=benchmark, dscore_ledger=ledger, rulepack_readiness=readiness,
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert "rulepack-not-release-ready" in decision.blockers
    assert "rulepack-manifest-digest-missing" in decision.blockers


def test_reviewed_frozen_rulepack_allows_base_gate_result():
    model, binding, facts, ledger, benchmark = fixtures()
    readiness = RulepackReadiness(
        rulepack_id=binding.rulepack_id,
        ready=True,
        blockers=(),
        manifest_sha256="c"*64,
        source_ids=("wag-source",),
    )
    decision = evaluate_validated_apparatus_promotion(
        model=model, binding=binding, accepted_facts=facts,
        benchmark=benchmark, dscore_ledger=ledger, rulepack_readiness=readiness,
    )
    assert decision.status is PromotionStatus.INTEGRATED_POST_ROUTINE
    assert decision.blockers == ()
