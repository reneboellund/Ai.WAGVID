import hashlib
import json

import pytest

from ai_wagvid.media_timeline_handoff import ffprobe_import_payload, load_worker_timeline
from ai_wagvid.media_worker import MediaWorkerError


def timeline(source_hash):
    return {
        "schema": "ai.wagvid.ffprobe-frame-timeline.v1",
        "source_sha256": source_hash,
        "source_size_bytes": 123,
        "created_at": "2026-08-17T09:30:00+00:00",
        "ffprobe_version": "ffprobe version test",
        "command_digest": "b" * 64,
        "raw_payload_sha256": "c" * 64,
        "frame_count": 2,
        "first_timestamp_seconds": 0.0,
        "last_timestamp_seconds": 0.041,
        "variable_frame_rate_observed": False,
        "frames": [
            {
                "index": 0,
                "best_effort_timestamp_time": 0.0,
                "pts_time": 0.0,
                "pkt_duration_time": 0.04,
                "key_frame": True,
            },
            {
                "index": 1,
                "best_effort_timestamp_time": 0.041,
                "pts_time": 0.041,
                "pkt_duration_time": 0.041,
                "key_frame": False,
            },
        ],
    }


def test_handoff_requires_exact_source_and_artifact_hash(tmp_path):
    source_hash = "a" * 64
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(timeline(source_hash)))
    artifact_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    loaded = load_worker_timeline(
        path,
        expected_source_sha256=source_hash,
        expected_artifact_sha256=artifact_hash,
    )
    assert loaded["source_sha256"] == source_hash

    with pytest.raises(MediaWorkerError, match="different source"):
        load_worker_timeline(path, expected_source_sha256="f" * 64)
    with pytest.raises(MediaWorkerError, match="artifact SHA"):
        load_worker_timeline(
            path,
            expected_source_sha256=source_hash,
            expected_artifact_sha256="0" * 64,
        )


def test_ffprobe_handoff_preserves_vfr_timestamps_and_keyframes_without_inventing_fields():
    payload = ffprobe_import_payload(timeline("a" * 64))
    assert list(payload) == ["frames"]
    assert payload["frames"][0] == {
        "best_effort_timestamp_time": "0.000000000",
        "key_frame": 1,
        "pts_time": "0.000000000",
        "pkt_duration_time": "0.040000000",
    }
    assert payload["frames"][1]["best_effort_timestamp_time"] == "0.041000000"
    assert payload["frames"][1]["key_frame"] == 0
    assert "dts_time" not in payload["frames"][1]
    assert "r_frame_rate" not in payload["frames"][1]


def test_handoff_rejects_non_contiguous_indices_and_non_monotonic_timeline():
    value = timeline("a" * 64)
    value["frames"][1]["index"] = 3
    with pytest.raises(MediaWorkerError, match="indices"):
        ffprobe_import_payload(value)

    value = timeline("a" * 64)
    value["frames"][1]["best_effort_timestamp_time"] = -0.1
    with pytest.raises(MediaWorkerError, match="non-monotonic"):
        ffprobe_import_payload(value)
