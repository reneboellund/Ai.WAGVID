import pytest

from ai_wagvid.motion_features import (
    body_axis_degrees,
    extract_motion_observations,
    pose_motion,
    segment_activity,
)
from ai_wagvid.perception import Keypoint, PoseFrame, Visibility


def pose(timestamp, x=0.0, *, camera="cam", confidence=0.9):
    points = (
        Keypoint("left_hip", x + 0.4, 0.6, confidence),
        Keypoint("right_hip", x + 0.6, 0.6, confidence),
        Keypoint("left_shoulder", x + 0.4, 0.3, confidence),
        Keypoint("right_shoulder", x + 0.6, 0.3, confidence),
        Keypoint("left_ankle", x + 0.4, 0.9, confidence),
        Keypoint("right_ankle", x + 0.6, 0.9, confidence),
    )
    return PoseFrame(timestamp, points, Visibility.VISIBLE, camera)


def test_motion_and_axis_are_framework_independent():
    assert pose_motion(pose(0, 0), pose(0.5, 0.1)) == pytest.approx(0.2)
    assert body_axis_degrees(pose(0)) == pytest.approx(-90)


def test_hysteresis_segments_motion_and_preserves_frame_evidence():
    frames = [pose(0), pose(0.5), pose(1.0, 0.1), pose(1.5, 0.2), pose(2.0, 0.2), pose(2.5, 0.2)]
    segments = segment_activity(frames, quiet_seconds=0.5)
    assert len(segments) == 1
    assert segments[0].interval.start_s == 0.5
    assert segments[0].evidence_frame_ids


def test_contact_is_only_a_candidate_and_provenance_is_complete():
    observations = extract_motion_observations(
        [pose(1)], source_id="video", producer="feature-baseline",
        producer_version="1", config_digest="a" * 64, support_y=0.9,
    )
    contact = next(item for item in observations if item.kind == "support_contact_candidate")
    assert contact.measurements["state"] == "POSSIBLE_CONTACT"
    assert contact.provenance.config_digest == "a" * 64


def test_cross_camera_motion_fails_closed():
    with pytest.raises(ValueError, match="one camera"):
        pose_motion(pose(0), pose(1, camera="other"))
