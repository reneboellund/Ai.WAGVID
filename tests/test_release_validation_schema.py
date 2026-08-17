from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.domain import Apparatus
from ai_wagvid.validation_governance import (
    BenchmarkSlice,
    DatasetEvidence,
    DatasetRightsStatus,
    MetricComparator,
    MetricResult,
    PromotionGate,
    PromotionPolicy,
    ReleaseValidationManifest,
    ValidationLayer,
    ValidationRequirement,
    ValidationRun,
    evaluate_promotion,
)
from wagvid_rules.validation import load_schema


ROOT = Path(__file__).parents[1]
SCHEMA = load_schema(ROOT / "schemas" / "release-validation-v1.schema.json")
T0 = datetime(2026, 8, 17, 17, 30, tzinfo=UTC)


def test_actual_release_validation_serializer_matches_public_schema():
    dataset = DatasetEvidence(
        dataset_id="rights-cleared-fixture",
        dataset_digest="1" * 64,
        rights_status=DatasetRightsStatus.CLEARED,
        split_manifest_digest="2" * 64,
        rights_reference="fixture-rights",
        rights_digest="3" * 64,
    )
    run = ValidationRun(
        run_id="run-1",
        layer=ValidationLayer.SEGMENTATION,
        benchmark_slice=BenchmarkSlice(
            dataset=dataset,
            sample_count=120,
            apparatus=Apparatus.BB,
            camera_condition="broadcast",
            skill_family="fixture-family",
            challenge_tags=("ood",),
        ),
        release_digest="4" * 64,
        model_bundle_digest="5" * 64,
        rulepack_digest="6" * 64,
        software_digest="7" * 64,
        runtime_manifest_digest="8" * 64,
        metrics=(
            MetricResult(
                metric_id="top-k-error",
                value=Decimal("0.05"),
                comparator=MetricComparator.AT_MOST,
                threshold=Decimal("0.10"),
                unit="rate",
            ),
            MetricResult(
                metric_id="unresolved-rate",
                value=Decimal("0.08"),
                comparator=MetricComparator.AT_MOST,
                threshold=Decimal("0.15"),
                unit="rate",
                waivable=False,
            ),
        ),
        started_at=T0,
        completed_at=T0 + timedelta(minutes=10),
    )
    policy = PromotionPolicy(
        policy_id="post-event-prod-v1",
        gate=PromotionGate.PRODUCTION_POST_EVENT,
        requirements=(
            ValidationRequirement(
                requirement_id="bb-broadcast-ood",
                layer=ValidationLayer.SEGMENTATION,
                metric_ids=("top-k-error", "unresolved-rate"),
                minimum_sample_count=100,
                apparatus=Apparatus.BB,
                camera_condition="broadcast",
                skill_family="fixture-family",
                required_challenge_tags=("ood",),
            ),
        ),
    )
    decision = evaluate_promotion(
        policy,
        (run,),
        release_digest="4" * 64,
        evaluated_at=T0 + timedelta(minutes=20),
    )
    manifest = ReleaseValidationManifest(
        manifest_id="release-validation-1",
        release_digest="4" * 64,
        model_bundle_digest="5" * 64,
        rulepack_digest="6" * 64,
        software_digest="7" * 64,
        promotion=decision,
        known_limitations=("fixed-end camera not yet validated",),
        created_at=T0 + timedelta(minutes=21),
    )
    errors = list(
        Draft202012Validator(
            SCHEMA,
            format_checker=FormatChecker(),
        ).iter_errors(manifest.normalized_dict())
    )
    assert errors == []
