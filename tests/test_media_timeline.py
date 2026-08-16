import hashlib
import io
from fractions import Fraction

import pytest

from ai_wagvid.media_timeline import (
    FrameTimestamp,
    build_timeline,
    parse_ffprobe_frames,
    sha256_stream,
)


def test_stream_hash_and_canonical_timeline_are_deterministic():
    digest, size = sha256_stream(io.BytesIO(b"video"))
    assert digest == hashlib.sha256(b"video").hexdigest()
    assert size == 5
    frames = tuple(FrameTimestamp(i, i * 40, i * 40, i * 40, 40, i == 0) for i in range(3))
    timeline = build_timeline(source_sha256=digest, time_base=Fraction(1, 1000), frames=frames)
    assert timeline.timestamp_s(2) == pytest.approx(0.08)
    assert timeline.frame_at_or_before(0.07).frame_index == 1
    assert len(timeline.digest) == 64


def test_vfr_duplicate_backward_and_gap_diagnostics_are_preserved():
    ticks = [0, 40, 40, 30, 200]
    frames = tuple(FrameTimestamp(i, tick, tick, tick, None, False) for i, tick in enumerate(ticks))
    timeline = build_timeline(source_sha256="a" * 64, time_base=Fraction(1, 1000), frames=frames)
    assert timeline.diagnostics.variable_frame_rate
    assert timeline.diagnostics.duplicate_timestamp_indices == (2,)
    assert timeline.diagnostics.non_monotonic_indices == (3,)
    assert timeline.diagnostics.suspected_gap_indices == (4,)


def test_ffprobe_frame_parser_preserves_pts_dts_and_timebase():
    timeline = parse_ffprobe_frames({
        "streams": [{"codec_type": "video", "time_base": "1/90000"}],
        "frames": [{"media_type": "video", "stream_index": 0, "pts": "9000", "pkt_dts": "8990", "best_effort_timestamp": "9000", "duration": "3000", "key_frame": 1}],
    }, source_sha256="b" * 64)
    assert timeline.frames[0].dts == 8990
    assert timeline.timestamp_s(0) == pytest.approx(0.1)


def test_missing_frame_timestamp_fails_instead_of_inventing_one():
    with pytest.raises(ValueError, match="no recoverable timestamp"):
        parse_ffprobe_frames({"streams": [{"codec_type": "video", "time_base": "1/1000"}], "frames": [{}]}, source_sha256="c" * 64)
