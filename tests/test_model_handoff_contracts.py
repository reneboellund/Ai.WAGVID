from dataclasses import fields

import pytest

from ai_wagvid.actions import ActionSegment, SkillAlternative
from ai_wagvid.domain import Apparatus, Provenance, TimeRange
from ai_wagvid.quality import QualityAssessment

PROVENANCE = Provenance(source_id="fixture", producer="test", producer_version="1")


def test_action_segments_preserve_ranked_alternatives_and_unknown_probability():
    segment = ActionSegment(
        segment_id="seg-1",
        interval=TimeRange(1.0, 2.4),
        apparatus=Apparatus.SR,
        alternatives=(
            SkillAlternative("mag-sr-a", 0.7),
            SkillAlternative("mag-sr-b", 0.2),
        ),
        unknown_probability=0.1,
        provenance=PROVENANCE,
    )
    assert segment.apparatus == Apparatus.SR
    with pytest.raises(ValueError):
        ActionSegment(
            segment_id="bad",
            interval=TimeRange(0, 1),
            apparatus=Apparatus.FX,
            alternatives=(SkillAlternative("a", 0.2), SkillAlternative("b", 0.7)),
            unknown_probability=0.1,
            provenance=PROVENANCE,
        )


def test_aqa_contract_cannot_masquerade_as_fig_score_ledger():
    field_names = {item.name for item in fields(QualityAssessment)}
    assert not {"d_score", "e_score", "final_score"} & field_names
    assessment = QualityAssessment(
        model_id="caflow-challenger",
        apparatus=Apparatus.BB,
        normalized_quality=7.25,
        calibration_id="wag-bb-heldout-v1",
        confidence=0.6,
        provenance=PROVENANCE,
    )
    assert assessment.normalized_quality == 7.25
    with pytest.raises(ValueError):
        QualityAssessment(
            model_id="bad",
            apparatus=Apparatus.BB,
            normalized_quality=11,
            calibration_id="",
            confidence=1,
            provenance=PROVENANCE,
        )


def test_domain_contains_all_wag_and_mag_apparatus_codes():
    assert {item.value for item in Apparatus} == {"VT", "UB", "BB", "FX", "PH", "SR", "PB", "HB"}
