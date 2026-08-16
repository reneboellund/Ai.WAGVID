from dataclasses import fields

import pytest

from ai_wagvid.domain import Apparatus, Provenance, TimeRange
from ai_wagvid.interpretation import ElementAlternative, ElementInterpretation
from ai_wagvid.perception import MotionObservation, PerceptionBundle


def test_perception_bundle_contains_no_score_contract() -> None:
    field_names = {field.name for field in fields(PerceptionBundle)}
    assert not {"d_score", "e_score", "final_score"} & field_names


def test_motion_observation_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        MotionObservation(
            observation_id="obs-1",
            kind="landing_contact",
            interval=TimeRange(1.0, 1.1),
            confidence=1.1,
            evidence_frame_ids=("frame-25",),
            measurements={},
            provenance=Provenance("media-1", "model", "1.0"),
        )


def test_interpretation_keeps_ranked_alternatives_and_unknown() -> None:
    interpretation = ElementInterpretation(
        segment_id="segment-1",
        apparatus=Apparatus.UB,
        alternatives=(
            ElementAlternative("wag.ub.element-x", 0.87, ("obs-1",)),
            ElementAlternative("wag.ub.element-y", 0.11, ("obs-2",)),
        ),
        unknown_probability=0.02,
        supporting_observation_ids=("obs-1", "obs-2"),
        interpreter_id="temporal-model@1",
    )
    assert interpretation.alternatives[0].element_id == "wag.ub.element-x"
    assert interpretation.needs_review is False


def test_interpretation_rejects_unranked_candidates() -> None:
    with pytest.raises(ValueError, match="ranked"):
        ElementInterpretation(
            segment_id="segment-1",
            apparatus=Apparatus.FX,
            alternatives=(
                ElementAlternative("candidate-a", 0.2, ()),
                ElementAlternative("candidate-b", 0.7, ()),
            ),
            unknown_probability=0.1,
            supporting_observation_ids=(),
            interpreter_id="temporal-model@1",
        )
