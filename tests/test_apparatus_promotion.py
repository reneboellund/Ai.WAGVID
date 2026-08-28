from datetime import UTC, datetime

import pytest

from ai_wagvid.apparatus_promotion import (
    ApparatusAcceptedFacts,
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    ApparatusPromotionError,
    ApparatusRulepackBinding,
    BenchmarkMetric,
    BenchmarkRunState,
    BenchmarkSliceResult,
    PromotionStatus,
    SliceStatus,
    evaluate_accepted_dscore,
    evaluate_apparatus_promotion,
)
from ai_wagvid.domain import Apparatus
from ai_wagvid.dscore import (
    AcceptedElementFact,
    CountingPolicy,
    DScorePolicy,
    ElementRule,
)


T0 = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def model(apparatus=Apparatus.VT):
    return ApparatusModelBundle(
        model_bundle_id="vt-model-fixture",
        apparatus=apparatus,
        adapter_id="fixture-adapter",
        adapter_version="1",
        checkpoint_sha256="1" * 64,
        config_sha256="2" * 64,
        label_map_sha256="3" * 64,
        training_dataset_manifest_sha256="4" * 64,
        training_rights_ref="fixture-rights-cleared",
        framework="fixture-framework",
        framework_version="1.0",
        created_at=T0,
    )


def policy(apparatus=Apparatus.VT):
    return DScorePolicy(
        rulepack_id="wag-fixture-2025-2028",
        rulepack_digest="5" * 64,
        apparatus=apparatus,
        units_per_point=10,
        elements=(ElementRule("VT.fixture-a", 40, "fixture-a", frozenset({"family-a"})),),
        counting=CountingPolicy(max_counted_elements=1),
    )


def accepted(m):
    return ApparatusAcceptedFacts(
        apparatus=m.apparatus,
        model_bundle_digest=m.digest,
        evidence_bundle_digest="6" * 64,
        review_decision_digest="7" * 64,
        elements=(AcceptedElementFact("fact-1", 0, ("VT.fixture-a",), ("evidence-1",)),),
    )


def binding(p):
    return ApparatusRulepackBinding.from_policy(
        p,
        reviewed_by="rules-reviewer-1",
        reviewer_qualification_ref="qualified-wag-rules-reviewer",
        reviewed_at=T0,
    )


def passing_slice(slice_id="camera-side"):
    return BenchmarkSliceResult(
        slice_id=slice_id,
        dimensions=(("camera", "side"), ("fps", "50")),
        metrics=(BenchmarkMetric("top1-accuracy", 920, 900, True),),
        status=SliceStatus.PASS,
        sample_count=25,
    )


def benchmark(m, b, *, run_state=BenchmarkRunState.EXECUTED, slices=None, required=("camera-side",)):
    return ApparatusBenchmarkReport(
        benchmark_id="vt-benchmark-fixture",
        apparatus=m.apparatus,
        run_state=run_state,
        model_bundle_digest=m.digest,
        rulepack_digest=b.rulepack_digest,
        benchmark_manifest_sha256="8" * 64,
        validation_dataset_manifest_sha256="9" * 64,
        split_manifest_sha256="a" * 64,
        rights_ref="validation-rights-cleared",
        hardware_runtime_manifest_sha256="b" * 64,
        slices=tuple(slices or (passing_slice(),)),
        required_slice_ids=required,
        executed_at=T0 if run_state is BenchmarkRunState.EXECUTED else None,
    )


def test_accepted_facts_evaluate_only_against_matching_reviewed_policy():
    m = model()
    p = policy()
    b = binding(p)
    ledger = evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=accepted(m))
    assert ledger.apparatus is Apparatus.VT
    assert ledger.rulepack_digest == b.rulepack_digest
    assert ledger.policy_digest == b.dscore_policy_digest
    assert ledger.resolved_score == "4.0"


def test_rulepack_policy_digest_mismatch_fails_closed():
    m = model()
    p = policy()
    b = ApparatusRulepackBinding(
        apparatus=Apparatus.VT,
        rulepack_id=p.rulepack_id,
        rulepack_digest=p.rulepack_digest,
        dscore_policy_digest="c" * 64,
        reviewed_by="rules-reviewer-1",
        reviewer_qualification_ref="qualified-wag-rules-reviewer",
        reviewed_at=T0,
    )
    with pytest.raises(ApparatusPromotionError, match="policy digest"):
        evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=accepted(m))


def test_planned_benchmark_can_never_promote():
    m = model()
    p = policy()
    b = binding(p)
    facts = accepted(m)
    ledger = evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=facts)
    report = benchmark(m, b, run_state=BenchmarkRunState.PLANNED)
    decision = evaluate_apparatus_promotion(model=m, binding=b, accepted_facts=facts, benchmark=report, dscore_ledger=ledger)
    assert decision.status is PromotionStatus.BLOCKED
    assert "benchmark-not-executed" in decision.blockers


def test_required_failed_slice_blocks_promotion_even_if_other_slices_pass():
    m = model()
    p = policy()
    b = binding(p)
    facts = accepted(m)
    ledger = evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=facts)
    failed = BenchmarkSliceResult(
        slice_id="motion-blur",
        dimensions=(("challenge", "motion-blur"),),
        metrics=(BenchmarkMetric("top1-accuracy", 700, 900, True),),
        status=SliceStatus.FAIL,
        sample_count=20,
        failure_reason="below declared threshold",
    )
    report = benchmark(m, b, slices=(passing_slice(), failed), required=("camera-side", "motion-blur"))
    decision = evaluate_apparatus_promotion(model=m, binding=b, accepted_facts=facts, benchmark=report, dscore_ledger=ledger)
    assert decision.status is PromotionStatus.BLOCKED
    assert "required-benchmark-slices-not-passed" in decision.blockers


def test_benchmark_must_bind_exact_model_digest():
    m = model()
    p = policy()
    b = binding(p)
    facts = accepted(m)
    ledger = evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=facts)
    other_model = model(Apparatus.VT)
    object.__setattr__(other_model, "checkpoint_sha256", "d" * 64)
    report = benchmark(other_model, b)
    decision = evaluate_apparatus_promotion(model=m, binding=b, accepted_facts=facts, benchmark=report, dscore_ledger=ledger)
    assert decision.status is PromotionStatus.BLOCKED
    assert "benchmark-model-digest-mismatch" in decision.blockers


def test_missing_dscore_ledger_blocks_integrated_post_routine_promotion():
    m = model()
    p = policy()
    b = binding(p)
    facts = accepted(m)
    decision = evaluate_apparatus_promotion(model=m, binding=b, accepted_facts=facts, benchmark=benchmark(m, b), dscore_ledger=None)
    assert decision.status is PromotionStatus.BLOCKED
    assert "dscore-ledger-missing" in decision.blockers


def test_synthetic_happy_path_reaches_integrated_post_routine_gate_only():
    m = model()
    p = policy()
    b = binding(p)
    facts = accepted(m)
    ledger = evaluate_accepted_dscore(policy=p, binding=b, accepted_facts=facts)
    decision = evaluate_apparatus_promotion(model=m, binding=b, accepted_facts=facts, benchmark=benchmark(m, b), dscore_ledger=ledger)
    assert decision.status is PromotionStatus.INTEGRATED_POST_ROUTINE
    assert decision.blockers == ()


def test_passing_slice_cannot_hide_failed_metric():
    with pytest.raises(ApparatusPromotionError, match="failed metric"):
        BenchmarkSliceResult(
            slice_id="bad-pass",
            dimensions=(("camera", "broadcast"),),
            metrics=(BenchmarkMetric("error-ms", 150, 100, False),),
            status=SliceStatus.PASS,
            sample_count=10,
        )
