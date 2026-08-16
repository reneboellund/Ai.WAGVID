import pytest

from ai_wagvid.pose_benchmark import (
    KeypointEvaluation,
    PoseBenchmarkCase,
    evaluate_pose_benchmark,
)


def case(case_id="one", apparatus="BB", camera="fixed-side"):
    return PoseBenchmarkCase(
        case_id, apparatus, camera, 0.5,
        (
            KeypointEvaluation("wrist", (0.1, 0.1), (0.1, 0.15), 0.9),
            KeypointEvaluation("ankle", None, (0.5, 0.8), 0.1),
            KeypointEvaluation("hidden", None, None, 0.05),
        ),
        inference_ms=20, peak_ram_mb=500, peak_vram_mb=1000,
        slices=("challenge:occlusion",),
    )


def test_pose_metrics_are_sliced_by_apparatus_camera_and_challenge():
    report = evaluate_pose_benchmark([case()])
    assert report["overall"]["pck"] == pytest.approx(1)
    assert report["overall"]["detected_expected_rate"] == pytest.approx(0.5)
    assert "apparatus:BB" in report["slices"]
    assert "camera:fixed-side" in report["slices"]
    assert "challenge:occlusion" in report["slices"]


def test_duplicate_cases_and_invalid_threshold_fail_closed():
    with pytest.raises(ValueError, match="unique"):
        evaluate_pose_benchmark([case(), case()])
    with pytest.raises(ValueError, match="threshold"):
        evaluate_pose_benchmark([case()], pck_threshold=0)
