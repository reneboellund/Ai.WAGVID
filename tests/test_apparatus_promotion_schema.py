import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.apparatus_promotion import (
    ApparatusBenchmarkReport,
    ApparatusModelBundle,
    BenchmarkMetric,
    BenchmarkRunState,
    BenchmarkSliceResult,
    SliceStatus,
)
from ai_wagvid.apparatus_promotion_exports import (
    apparatus_benchmark_payload,
    apparatus_model_bundle_payload,
)
from ai_wagvid.domain import Apparatus


ROOT = Path(__file__).parents[1]
MODEL_SCHEMA = json.loads((ROOT / "schemas" / "apparatus-model-bundle-v1.schema.json").read_text(encoding="utf-8"))
BENCHMARK_SCHEMA = json.loads((ROOT / "schemas" / "apparatus-benchmark-report-v1.schema.json").read_text(encoding="utf-8"))
MODEL_VALIDATOR = Draft202012Validator(MODEL_SCHEMA, format_checker=FormatChecker())
BENCHMARK_VALIDATOR = Draft202012Validator(BENCHMARK_SCHEMA, format_checker=FormatChecker())
T0 = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def model():
    return ApparatusModelBundle(
        model_bundle_id="fixture-model",
        apparatus=Apparatus.VT,
        adapter_id="fixture-adapter",
        adapter_version="1",
        checkpoint_sha256="1" * 64,
        config_sha256="2" * 64,
        label_map_sha256="3" * 64,
        training_dataset_manifest_sha256="4" * 64,
        training_rights_ref="rights-cleared-fixture",
        framework="fixture-framework",
        framework_version="1.0",
        created_at=T0,
    )


def benchmark(m):
    return ApparatusBenchmarkReport(
        benchmark_id="fixture-benchmark",
        apparatus=Apparatus.VT,
        run_state=BenchmarkRunState.EXECUTED,
        model_bundle_digest=m.digest,
        rulepack_digest="5" * 64,
        benchmark_manifest_sha256="6" * 64,
        validation_dataset_manifest_sha256="7" * 64,
        split_manifest_sha256="8" * 64,
        rights_ref="rights-cleared-validation",
        hardware_runtime_manifest_sha256="9" * 64,
        slices=(
            BenchmarkSliceResult(
                slice_id="fixed-side",
                dimensions=(("camera", "fixed-side"),),
                metrics=(BenchmarkMetric("top1", 920, 900, True),),
                status=SliceStatus.PASS,
                sample_count=20,
            ),
        ),
        required_slice_ids=("fixed-side",),
        executed_at=T0,
    )


def test_model_bundle_payload_validates():
    assert list(MODEL_VALIDATOR.iter_errors(apparatus_model_bundle_payload(model()))) == []


def test_model_bundle_schema_rejects_official_score_leakage():
    value = apparatus_model_bundle_payload(model())
    value["official_score_feature"] = True
    errors = list(MODEL_VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_benchmark_payload_validates():
    m = model()
    assert list(BENCHMARK_VALIDATOR.iter_errors(apparatus_benchmark_payload(benchmark(m)))) == []


def test_benchmark_schema_rejects_posthoc_claim_fields():
    m = model()
    value = apparatus_benchmark_payload(benchmark(m))
    value["competition_grade"] = True
    value["official_judging_ready"] = True
    errors = list(BENCHMARK_VALIDATOR.iter_errors(value))
    assert any("Additional properties are not allowed" in error.message for error in errors)
