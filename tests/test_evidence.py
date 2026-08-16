from datetime import UTC, datetime
from fractions import Fraction

import pytest

from ai_wagvid.calibration import ApparatusCalibration
from ai_wagvid.domain import Apparatus, TimeRange
from ai_wagvid.evidence import EvidenceMismatch, create_evidence_reference, resolve_evidence
from ai_wagvid.media_timeline import FrameTimestamp, build_timeline


def timeline(source="a" * 64):
    return build_timeline(
        source_sha256=source, time_base=Fraction(1, 1000),
        frames=tuple(
            FrameTimestamp(i, i * 40, i * 40, i * 40, 40, i == 0) for i in range(5)
        ),
    )


def calibration(source="a" * 64, revision=1):
    return ApparatusCalibration(
        f"bb-r{revision}", "cam-1", Apparatus.BB, source, revision, TimeRange(0, 10),
        {"beam_start": [0.1, 0.5], "beam_end": [0.9, 0.5]},
        datetime(2026, 1, 1, tzinfo=UTC), "reviewer",
    )


def test_evidence_roundtrip_resolves_identical_source_frames():
    source, geometry = timeline(), calibration()
    reference = create_evidence_reference(
        evidence_id="ev-1", timeline=source, camera_id="cam-1",
        start_timestamp_s=0.05, end_timestamp_s=0.13,
        producer="review-ui", producer_version="1", calibration=geometry,
    )
    resolved = resolve_evidence(reference, timeline=source, calibration=geometry)
    assert [item.frame_index for item in resolved.frames] == [1, 2, 3]
    assert len(reference.digest) == 64


def test_changed_source_or_calibration_revision_is_rejected():
    source, geometry = timeline(), calibration()
    reference = create_evidence_reference(
        evidence_id="ev", timeline=source, camera_id="cam-1",
        start_timestamp_s=0, end_timestamp_s=0.1,
        producer="model", producer_version="1", calibration=geometry,
    )
    with pytest.raises(EvidenceMismatch, match="timeline/source"):
        resolve_evidence(reference, timeline=timeline("b" * 64), calibration=geometry)
    with pytest.raises(EvidenceMismatch, match="calibration revision"):
        resolve_evidence(reference, timeline=source, calibration=calibration(revision=2))
