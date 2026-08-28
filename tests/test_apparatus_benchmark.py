import pytest

from ai_wagvid.apparatus_benchmark import (
    ApparatusBenchmarkError,
    RankedIdentityExample,
    StateExample,
    TimingExample,
    evaluate_ranked_identity,
    evaluate_state_agreement,
    evaluate_timing,
)


def test_ranked_identity_metrics_cover_top1_topk_and_ood():
    metrics = evaluate_ranked_identity(
        (
            RankedIdentityExample("known-1", "VT.a", ("VT.a", "VT.b"), 50),
            RankedIdentityExample("known-2", "VT.b", ("VT.a", "VT.b"), 100),
            RankedIdentityExample("ood-1", None, (), 900),
            RankedIdentityExample("ood-2", None, ("VT.a",), 200),
        ),
        top_k=2,
        ood_threshold_milli=700,
    )
    assert metrics.sample_count == 4
    assert metrics.top1_accuracy_milli == 500
    assert metrics.topk_recall_milli == 1000
    assert metrics.ood_detection_tpr_milli == 500
    assert metrics.known_false_ood_rate_milli == 0


def test_identity_metrics_do_not_force_known_metrics_when_only_ood_samples_exist():
    metrics = evaluate_ranked_identity(
        (RankedIdentityExample("ood-1", None, (), 900),),
        top_k=3,
        ood_threshold_milli=700,
    )
    assert metrics.top1_accuracy_milli is None
    assert metrics.topk_recall_milli is None
    assert metrics.ood_detection_tpr_milli == 1000


def test_timing_metrics_report_misses_separately_from_timing_error():
    metrics = evaluate_timing(
        (
            TimingExample("event-1", reference_ms=1000, predicted_ms=1010),
            TimingExample("event-2", reference_ms=2000, predicted_ms=1960),
            TimingExample("event-3", reference_ms=3000, predicted_ms=None),
        )
    )
    assert metrics.sample_count == 3
    assert metrics.detected_count == 2
    assert metrics.missed_count == 1
    assert metrics.detection_recall_milli == 667
    assert metrics.mean_absolute_error_ms == 25
    assert metrics.median_absolute_error_ms == 25
    assert metrics.max_absolute_error_ms == 40


def test_state_agreement_retains_exact_mismatch_evidence():
    metrics = evaluate_state_agreement(
        (
            StateExample("s1", "continuous", "continuous"),
            StateExample("s2", "interrupted", "unresolved"),
            StateExample("s3", "unresolved", "unresolved"),
        )
    )
    assert metrics.exact_agreement_milli == 667
    assert metrics.mismatches == (("s2", "interrupted", "unresolved"),)


def test_empty_benchmarks_fail_closed():
    with pytest.raises(ApparatusBenchmarkError):
        evaluate_timing(())
    with pytest.raises(ApparatusBenchmarkError):
        evaluate_state_agreement(())
    with pytest.raises(ApparatusBenchmarkError):
        evaluate_ranked_identity((), top_k=1, ood_threshold_milli=500)
