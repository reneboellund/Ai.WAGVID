import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_wagvid.benchmark import (
    BenchmarkCase,
    BenchmarkRun,
    RankedCandidate,
    evaluate_benchmark,
)


def run():
    return BenchmarkRun(
        run_id="run-1",
        dataset_id="frozen-set",
        dataset_version="1",
        split="test",
        model_profile="challenger@1",
        model_bundle_digest="a" * 64,
        software_revision="commit-1",
        rulepack_id=None,
        started_at=datetime(2026, 8, 16, tzinfo=UTC),
    )


def cases():
    return (
        BenchmarkCase(
            "case-1",
            "BB",
            "element-a",
            (RankedCandidate("element-a", 0.8), RankedCandidate("element-b", 0.1)),
            0.1,
            event_timing_error_ms=-20,
            slices=("camera:fixed", "visibility:clear"),
        ),
        BenchmarkCase(
            "case-2",
            "BB",
            "element-b",
            (RankedCandidate("element-a", 0.6), RankedCandidate("element-b", 0.3)),
            0.1,
            event_timing_error_ms=40,
            slices=("camera:fixed", "visibility:occluded"),
        ),
        BenchmarkCase(
            "case-3",
            "FX",
            None,
            (RankedCandidate("element-c", 0.2),),
            0.8,
            slices=("camera:broadcast",),
        ),
    )


def test_report_has_accuracy_ood_timing_calibration_slices_and_provenance():
    report = evaluate_benchmark(run(), cases(), top_k=2)
    assert report["overall"]["top1_accuracy"] == 0.5
    assert report["overall"]["top2_accuracy"] == 1.0
    assert report["overall"]["unknown_recall"] == 1.0
    assert report["overall"]["mean_absolute_timing_error_ms"] == 30
    assert report["slices"]["apparatus:BB"]["case_count"] == 2
    assert report["run"]["dataset_version"] == "1"
    schema = json.loads(Path("schemas/benchmark-report-v1.schema.json").read_text())
    assert list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report)
    ) == []


def test_invalid_probabilities_order_split_and_duplicate_cases_fail_closed():
    with pytest.raises(ValueError, match="ranked"):
        BenchmarkCase(
            "case",
            "BB",
            "x",
            (RankedCandidate("x", 0.2), RankedCandidate("y", 0.7)),
            0.1,
        )
    with pytest.raises(ValueError, match="validation or test"):
        BenchmarkRun("r", "d", "1", "train", "p", "x", "c", None, datetime.now(UTC))
    with pytest.raises(ValueError, match="unique"):
        evaluate_benchmark(run(), (cases()[0], cases()[0]))
