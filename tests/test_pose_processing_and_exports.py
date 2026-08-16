import csv
import io
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_wagvid.actions import ActionSegment, SkillAlternative
from ai_wagvid.domain import Apparatus, Provenance, ScoreLedger, TimeRange
from ai_wagvid.exports import analysis_export_json, build_analysis_export, pose_frames_csv
from ai_wagvid.perception import Keypoint, PerceptionBundle, PoseFrame, Visibility
from ai_wagvid.pose_processing import (
    compute_joint_angle,
    extract_joint_angles,
    keypoint_map,
    normalize_skeleton,
    smooth_pose_sequence,
)
from ai_wagvid.quality import QualityAssessment

PROVENANCE = Provenance("fixture", "test", "1")


def point(name, x, y, confidence=1.0, z=None):
    return Keypoint(name, x, y, confidence, z)


def pose(timestamp=0.0, offset=0.0):
    return PoseFrame(
        timestamp,
        (
            point("left_shoulder", 1 + offset, 1),
            point("right_shoulder", 3 + offset, 1),
            point("left_hip", 1 + offset, 3),
            point("right_hip", 3 + offset, 3),
            point("left_knee", 1 + offset, 5),
            point("left_ankle", 1 + offset, 7),
        ),
        Visibility.VISIBLE,
        "camera-1",
    )


def test_normalization_centers_scales_and_compensates_rotation():
    normalized = keypoint_map(normalize_skeleton(pose()))
    hip_x = (normalized["left_hip"].x + normalized["right_hip"].x) / 2
    hip_y = (normalized["left_hip"].y + normalized["right_hip"].y) / 2
    shoulder_x = (normalized["left_shoulder"].x + normalized["right_shoulder"].x) / 2
    shoulder_y = (normalized["left_shoulder"].y + normalized["right_shoulder"].y) / 2
    assert hip_x == pytest.approx(0)
    assert hip_y == pytest.approx(0)
    assert shoulder_x == pytest.approx(0)
    assert shoulder_y == pytest.approx(-1)


def test_joint_angles_are_geometric_and_confidence_gated():
    straight = compute_joint_angle(point("a", 0, 0), point("knee", 1, 0), point("b", 2, 0))
    assert straight is not None
    assert straight.degrees == pytest.approx(180)
    right = compute_joint_angle(point("a", 0, 1), point("knee", 0, 0), point("b", 1, 0))
    assert right is not None
    assert right.degrees == pytest.approx(90)
    assert compute_joint_angle(
        point("a", 0, 1, 0.1), point("knee", 0, 0), point("b", 1, 0)
    ) is None
    assert extract_joint_angles(pose())[0].name == "left_hip"


def test_invalid_or_degenerate_pose_is_not_silently_scored():
    with pytest.raises(ValueError, match="requires"):
        normalize_skeleton(
            PoseFrame(0, (point("left_hip", 0, 0),), Visibility.VISIBLE, "camera")
        )
    assert compute_joint_angle(point("a", 0, 0), point("b", 0, 0), point("c", 1, 0)) is None
    duplicate = PoseFrame(
        0,
        (point("nose", 0, 0), point("nose", 1, 1)),
        Visibility.VISIBLE,
        "camera",
    )
    with pytest.raises(ValueError, match="duplicate"):
        keypoint_map(duplicate)


def test_smoothing_is_ordered_confidence_weighted_and_camera_isolated():
    frames = (pose(0, 0), pose(1, 9), pose(2, 0))
    smoothed = smooth_pose_sequence(frames, radius=1)
    assert keypoint_map(smoothed[1])["left_hip"].x == pytest.approx(4)
    with pytest.raises(ValueError, match="ordered"):
        smooth_pose_sequence((pose(2), pose(1)))


def test_json_and_csv_exports_are_versioned_and_keep_aqa_separate():
    perception = PerceptionBundle(
        media_id="media-1",
        apparatus=Apparatus.BB,
        interval=TimeRange(0, 4),
        pose_frames=(pose(),),
    )
    segment = ActionSegment(
        "segment-1",
        TimeRange(1, 2),
        Apparatus.BB,
        (SkillAlternative("bb-skill", 0.8),),
        0.2,
        PROVENANCE,
    )
    quality = QualityAssessment(
        "aqa-test", Apparatus.BB, 7.1, "calibration-1", 0.5, PROVENANCE
    )
    payload = build_analysis_export(
        perception=perception,
        segments=(segment,),
        score_ledger=ScoreLedger("rules@1", d_score=4.2),
        quality=quality,
    )
    assert payload["schema_version"] == "1.0.0"
    assert payload["score_ledger"]["d_score"] == 4.2
    assert payload["advisory_quality"]["normalized_quality"] == 7.1
    assert "final_score" not in payload["advisory_quality"]
    assert json.loads(analysis_export_json(perception=perception))["apparatus"] == "BB"
    rows = list(csv.DictReader(io.StringIO(pose_frames_csv(perception))))
    assert rows[0]["schema_version"] == "1.0.0"
    assert rows[0]["media_id"] == "media-1"

    schema_path = Path(__file__).parents[1] / "schemas" / "model-analysis-export-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_export_rejects_cross_apparatus_mixing_and_non_finite_json():
    perception = PerceptionBundle("m", Apparatus.FX, TimeRange(0, 1))
    quality = QualityAssessment("q", Apparatus.VT, 5, "c", None, PROVENANCE)
    with pytest.raises(ValueError, match="apparatus"):
        build_analysis_export(perception=perception, quality=quality)
    invalid = PerceptionBundle(
        "m",
        Apparatus.FX,
        TimeRange(0, 1),
        metadata={"invalid": math.nan},
    )
    with pytest.raises(ValueError):
        analysis_export_json(perception=invalid)
