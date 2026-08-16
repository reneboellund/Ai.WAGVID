from types import SimpleNamespace

import pytest

from ai_wagvid.domain import Apparatus, TimeRange
from ai_wagvid.model_adapters import (
    CocoPoseAdapter,
    LabelMapping,
    LinearAQAAdapter,
    MediaPipePoseAdapter,
    MMActionAdapter,
)
from ai_wagvid.perception import Visibility


def test_mediapipe_result_becomes_canonical_normalized_pose():
    point = SimpleNamespace(x=0.25, y=0.5, z=-0.1, visibility=0.9)
    frame = MediaPipePoseAdapter().convert_result(
        SimpleNamespace(pose_landmarks=[[point] * 33]), timestamp_s=1.25, camera_id="phone-1"
    )
    assert frame.keypoints[0].name == "nose"
    assert frame.keypoints[0].z == pytest.approx(-0.1)
    assert frame.visibility is Visibility.VISIBLE


def test_coco_pixel_pose_is_normalized_and_provenance_is_retained():
    adapter = CocoPoseAdapter("rtmpose-m@1", "1.3.2")
    frame = adapter.convert(
        [[320, 240, 0.9]] * 17, timestamp_s=0.0, camera_id="cam",
        normalized=False, image_size=(640, 480),
    )
    bundle = adapter.bundle(
        media_id="video-1", apparatus=Apparatus.FX, interval=TimeRange(0, 1),
        frames=[frame], config_digest="a" * 64,
    )
    assert frame.keypoints[0].x == pytest.approx(0.5)
    assert bundle.metadata["provenance"].config_digest == "a" * 64


def test_action_adapter_maps_known_labels_and_routes_ambiguity_to_unknown():
    adapter = MMActionAdapter(
        "mmaction-finegym@1", "2.0", {
            0: LabelMapping("background", None, "excluded"),
            1: LabelMapping("source-skill", "wag.fx.candidate-1", "mapped"),
            2: LabelMapping("ambiguous", None, "ambiguous"),
        },
    )
    segment = adapter.convert_scores(
        [0.1, 0.7, 0.2], segment_id="seg-1", interval=TimeRange(2, 3),
        apparatus=Apparatus.FX, source_id="video-1",
    )
    assert segment.alternatives[0].label_id == "wag.fx.candidate-1"
    assert segment.unknown_probability == pytest.approx(0.3)


def test_aqa_is_calibrated_but_remains_advisory():
    adapter = LinearAQAAdapter("caflow@research", "rev", "heldout-v1", 20, 80, lambda *_: (50, 0.8))
    result = adapter.assess(media_id="video-1", apparatus=Apparatus.BB)
    assert result.normalized_quality == pytest.approx(5)
    assert result.diagnostics["raw_score"] == 50

