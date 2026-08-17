from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ai_wagvid.domain import Apparatus
from ai_wagvid.validation_governance import (
    BenchmarkSlice,
    DatasetEvidence,
    DatasetRightsStatus,
    MetricComparator,
    MetricResult,
    PromotionGate,
    PromotionPolicy,
    PromotionStatus,
    RegressionWaiver,
    ReleaseValidationManifest,
    ValidationGovernanceError,
    ValidationLayer,
    ValidationRequirement,
    ValidationRun,
    evaluate_promotion,
)


T0 = datetime(2026, 8, 17, 17, 0, tzinfo=UTC)
RELEASE = "a" * 64
MODEL = "b" * 64
RULES = "c" * 64
SOFTWARE = "d" * 64
RUNTIME = "e" * 64


def dataset(*, rights=DatasetRightsStatus.CLEARED, seed: str = "1") -> DatasetEvidence:
    return DatasetEvidence(
        dataset_id=f"dataset-{seed}",
        dataset_digest=seed * 64,
        rights_status=rights,
        split_manifest_digest=("f" if seed != "f" else "0") * 64,
        rights_reference="rights-fixture" if rights is DatasetRightsStatus.CLEARED else None,
        rights_digest="9" * 64 if rights is DatasetRightsStatus.CLEARED else None,
    )


def metric(
    metric_id: str,
    value: str,
    threshold: str,
    *,
    comparator=MetricComparator.AT_MOST,
    waivable: bool = True,
    unresolved: int = 0,
    unavailable: int = 0,
) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        value=Decimal(value),
        comparator=comparator,
        threshold=Decimal(threshold),
        unit="fixture-unit",
        waivable=waivable,
        unresolved_count=unresolved,
        unavailable_count=unavailable,
    )


def run(
    run_id: str,
    *,
    apparatus: Apparatus | None = Apparatus.BB,
    camera: str | None = "broadcast",
    challenge_tags: tuple[str, ...] = ("ood",),
    rights=DatasetRightsStatus.CLEARED,
    metrics: tuple[MetricResult, ...] | None = None,
    leakage: bool = False,
    rulepack_valid: bool = True,
    audit_valid: bool = True,
    media_valid: bool = True,
    completed_offset: int = 1,
    sample_count: int = 100,
    layer: ValidationLayer = ValidationLayer.SEGMENTATION,
) -> ValidationRun:
    return ValidationRun(
        run_id=run_id,
        layer=layer,
        benchmark_slice=BenchmarkSlice(
            dataset=dataset(rights=rights, seed=(run_id[0] if run_id[0] in "123456789abcdef" else "1")),
            sample_count=sample_count,
            apparatus=apparatus,
            camera_condition=camera,
            skill_family="fixture-family",
            challenge_tags=challenge_tags,
        ),
        release_digest=RELEASE,
        model_bundle_digest=MODEL,
        rulepack_digest=RULES,
        software_digest=SOFTWARE,
        runtime_manifest_digest=RUNTIME,
        metrics=metrics
        or (
            metric("top-k-error", "0.05", "0.10"),
            metric("unresolved-rate", "0.08", "0.15", waivable=False),
        ),
        started_at=T0,
        completed_at=T0 + timedelta(minutes=completed_offset),
        official_score_leakage_detected=leakage,
        rulepack_provenance_valid=rulepack_valid,
        audit_provenance_valid=audit_valid,
        source_media_integrity_valid=media_valid,
    )


def requirement(
    requirement_id: str = "bb-broadcast-ood",
    *,
    apparatus: Apparatus | None = Apparatus.BB,
    camera: str | None = "broadcast",
    challenge_tags: tuple[str, ...] = ("ood",),
    metrics: tuple[str, ...] = ("top-k-error", "unresolved-rate"),
    layer: ValidationLayer = ValidationLayer.SEGMENTATION,
) -> ValidationRequirement:
    return ValidationRequirement(
        requirement_id=requirement_id,
        layer=layer,
        metric_ids=metrics,
        minimum_sample_count=50,
        apparatus=apparatus,
        camera_condition=camera,
        skill_family="fixture-family" if apparatus is not None else None,
        required_challenge_tags=challenge_tags,
    )


def policy(*requirements: ValidationRequirement) -> PromotionPolicy:
    return PromotionPolicy(
        policy_id="production-post-event-v1",
        gate=PromotionGate.PRODUCTION_POST_EVENT,
        requirements=requirements or (requirement(),),
    )


def test_current_promotion_enum_contains_no_shadow_live_or_official_scoring_gate():
    values = {item.value for item in PromotionGate}
    assert values == {
        "research-fixture",
        "offline-component",
        "integrated-post-routine",
        "qualified-user-pilot",
        "production-post-event",
    }
    assert not any("live" in value or "shadow" in value or "official" in value for value in values)


def test_clean_required_slice_passes_and_release_claim_is_limited_to_that_slice():
    decision = evaluate_promotion(
        policy(),
        (run("1-clean"),),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert decision.status is PromotionStatus.PASSED
    assert decision.blockers == ()
    assert len(decision.validated_scopes) == 1
    scope = decision.validated_scopes[0]
    assert scope.apparatus is Apparatus.BB
    assert scope.camera_condition == "broadcast"
    assert scope.challenge_tags == ("ood",)
    assert scope.sample_count == 100
    assert len(scope.run_digest) == 64


def test_good_aggregate_metric_cannot_replace_missing_required_apparatus_slice():
    aggregate = run(
        "2-aggregate",
        apparatus=None,
        camera=None,
        challenge_tags=(),
        metrics=(metric("top-k-error", "0.01", "0.10"), metric("unresolved-rate", "0.01", "0.15", waivable=False)),
    )
    decision = evaluate_promotion(
        policy(requirement()),
        (aggregate,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert decision.blockers == ("requirement-unsatisfied:bb-broadcast-ood",)
    assert decision.validated_scopes == ()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"rights": DatasetRightsStatus.UNCLEARED}, "dataset-rights-uncleared"),
        ({"leakage": True}, "official-score-leakage"),
        ({"rulepack_valid": False}, "rulepack-provenance-invalid"),
        ({"audit_valid": False}, "audit-provenance-invalid"),
        ({"media_valid": False}, "source-media-integrity-invalid"),
    ],
)
def test_safety_and_provenance_hard_blockers_are_nonwaivable(kwargs, expected):
    blocked_run = run("3-hard", **kwargs)
    # A waiver targeting a failed/nominal metric cannot waive a hard blocker because the
    # evaluation model has no waiver target for hard-blocker codes.
    waiver = RegressionWaiver(
        waiver_id="waiver-hard-attempt",
        run_id=blocked_run.run_id,
        metric_id="top-k-error",
        approver_id="approver-1",
        reason="Attempted metric waiver must not bypass safety provenance",
        approved_at=T0,
        expires_at=T0 + timedelta(days=1),
    )
    decision = evaluate_promotion(
        policy(),
        (blocked_run,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
        waivers=(waiver,),
    )
    assert decision.status is PromotionStatus.BLOCKED
    detail = "|".join(decision.requirements[0].blockers)
    assert f"hard-blocker:{expected}" in detail
    assert decision.active_waiver_digests == ()


def test_failed_waivable_metric_can_be_time_bounded_with_named_approver():
    failed = run(
        "4-waivable",
        metrics=(
            metric("top-k-error", "0.20", "0.10", waivable=True),
            metric("unresolved-rate", "0.08", "0.15", waivable=False),
        ),
    )
    waiver = RegressionWaiver(
        waiver_id="waiver-1",
        run_id=failed.run_id,
        metric_id="top-k-error",
        approver_id="qualified-release-approver",
        reason="Time-bounded known regression accepted for fixture rollout",
        approved_at=T0,
        expires_at=T0 + timedelta(hours=2),
    )
    decision = evaluate_promotion(
        policy(),
        (failed,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
        waivers=(waiver,),
    )
    assert decision.status is PromotionStatus.PASSED
    assert decision.requirements[0].waived_metric_ids == ("top-k-error",)
    assert decision.active_waiver_digests == (waiver.digest,)


def test_expired_waiver_no_longer_satisfies_failed_metric():
    failed = run(
        "5-expired",
        metrics=(
            metric("top-k-error", "0.20", "0.10"),
            metric("unresolved-rate", "0.08", "0.15", waivable=False),
        ),
    )
    waiver = RegressionWaiver(
        waiver_id="waiver-expired",
        run_id=failed.run_id,
        metric_id="top-k-error",
        approver_id="approver-1",
        reason="Temporary exception",
        approved_at=T0,
        expires_at=T0 + timedelta(minutes=30),
    )
    decision = evaluate_promotion(
        policy(),
        (failed,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
        waivers=(waiver,),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert "metric-failed:top-k-error" in "|".join(decision.requirements[0].blockers)
    assert decision.active_waiver_digests == ()


def test_nonwaivable_required_metric_cannot_be_waived():
    failed = run(
        "6-nonwaivable",
        metrics=(
            metric("top-k-error", "0.05", "0.10"),
            metric("unresolved-rate", "0.30", "0.15", waivable=False),
        ),
    )
    waiver = RegressionWaiver(
        waiver_id="waiver-invalid",
        run_id=failed.run_id,
        metric_id="unresolved-rate",
        approver_id="approver-1",
        reason="Cannot waive this metric",
        approved_at=T0,
        expires_at=T0 + timedelta(hours=2),
    )
    decision = evaluate_promotion(
        policy(),
        (failed,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
        waivers=(waiver,),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert "metric-non-waivable:unresolved-rate" in "|".join(decision.requirements[0].blockers)


def test_missing_unresolved_or_abstention_metric_blocks_even_when_accuracy_metric_passes():
    accuracy_only = run(
        "7-missing-review-metric",
        metrics=(metric("top-k-error", "0.03", "0.10"),),
    )
    decision = evaluate_promotion(
        policy(),
        (accuracy_only,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert "missing-metric:unresolved-rate" in "|".join(decision.requirements[0].blockers)


def test_missing_required_ood_challenge_slice_blocks_normal_slice_success():
    normal = run("8-normal", challenge_tags=("common",))
    decision = evaluate_promotion(
        policy(requirement(challenge_tags=("ood",))),
        (normal,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert decision.validated_scopes == ()


def test_multiple_requirements_claim_only_individually_validated_scopes():
    bb_req = requirement("bb", apparatus=Apparatus.BB)
    fx_req = requirement("fx", apparatus=Apparatus.FX)
    bb = run("9-bb", apparatus=Apparatus.BB)
    decision = evaluate_promotion(
        policy(bb_req, fx_req),
        (bb,),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert decision.status is PromotionStatus.BLOCKED
    assert [scope.requirement_id for scope in decision.validated_scopes] == ["bb"]
    assert "requirement-unsatisfied:fx" in decision.blockers


def test_newer_clean_matching_run_is_selected_deterministically_over_older_run():
    older = run("a-old", completed_offset=1)
    newer = run("b-new", completed_offset=2)
    first = evaluate_promotion(
        policy(),
        (newer, older),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    second = evaluate_promotion(
        policy(),
        (older, newer),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    assert first.requirements[0].selected_run_digest == newer.digest
    assert second.requirements[0].selected_run_digest == newer.digest
    assert first.validated_scopes == second.validated_scopes


def test_release_validation_manifest_serializes_exact_validated_scope_and_limitations():
    decision = evaluate_promotion(
        policy(),
        (run("c-manifest"),),
        release_digest=RELEASE,
        evaluated_at=T0 + timedelta(hours=1),
    )
    manifest = ReleaseValidationManifest(
        manifest_id="release-validation-1",
        release_digest=RELEASE,
        model_bundle_digest=MODEL,
        rulepack_digest=RULES,
        software_digest=SOFTWARE,
        promotion=decision,
        known_limitations=("not validated for fixed-end camera",),
        created_at=T0 + timedelta(hours=1, minutes=1),
    )
    payload = manifest.normalized_dict()
    assert payload["promotion"]["gate"] == "production-post-event"
    assert payload["promotion"]["status"] == "passed"
    assert payload["promotion"]["validated_scopes"][0]["apparatus"] == "BB"
    assert payload["known_limitations"] == ["not validated for fixed-end camera"]
    assert len(manifest.digest) == 64


def test_metric_values_and_thresholds_must_be_finite_decimals():
    with pytest.raises(ValidationGovernanceError, match="finite Decimal"):
        MetricResult(
            metric_id="bad",
            value=Decimal("NaN"),
            comparator=MetricComparator.AT_MOST,
            threshold=Decimal("0.1"),
            unit="rate",
        )
