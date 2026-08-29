import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_wagvid.media_worker import (
    CommandResult,
    MediaStage,
    MediaWorkerError,
    ProxyProfile,
    WorkerTools,
    append_journal,
    ffmpeg_proxy_command,
    parse_ffprobe_frames,
    process_media,
    read_journal,
)


NOW = datetime(2026, 8, 17, 9, 30, tzinfo=UTC)


def probe_payload(times=(0.0, 0.04, 0.08, 0.13)):
    return json.dumps(
        {
            "frames": [
                {
                    "best_effort_timestamp_time": f"{value:.6f}",
                    "pts_time": f"{value:.6f}",
                    "pkt_duration_time": "0.040000",
                    "key_frame": 1 if index == 0 else 0,
                }
                for index, value in enumerate(times)
            ]
        }
    )


class FakeRunner:
    def __init__(self, *, fail_ffmpeg=False):
        self.calls = []
        self.fail_ffmpeg = fail_ffmpeg

    def run(self, argv, *, timeout_seconds):
        argv = tuple(argv)
        self.calls.append((argv, timeout_seconds))
        executable = Path(argv[0]).name
        if len(argv) == 2 and argv[1] == "-version":
            if "ffprobe" in executable:
                return CommandResult(stdout="ffprobe version 7.1-test\n")
            return CommandResult(stdout="ffmpeg version 7.1-test\n")
        if "ffprobe" in executable:
            return CommandResult(stdout=probe_payload())
        if "ffmpeg" in executable:
            if self.fail_ffmpeg:
                return CommandResult(stderr="synthetic transcode failure", returncode=9)
            output = Path(argv[-1])
            output.write_bytes(b"synthetic-proxy-bytes")
            return CommandResult()
        raise AssertionError(argv)


def test_proxy_command_preserves_presentation_timing_without_forcing_constant_fps(tmp_path):
    command = ffmpeg_proxy_command(
        WorkerTools(), tmp_path / "source.mp4", tmp_path / "proxy.partial.mp4", ProxyProfile()
    )
    joined = " ".join(command)
    assert "-copyts" in command
    assert "-start_at_zero" in command
    assert command[command.index("-fps_mode") + 1] == "passthrough"
    assert " -r " not in f" {joined} "
    assert "fps=" not in joined
    assert "shell=True" not in joined


def test_ffprobe_parser_accepts_vfr_but_rejects_non_monotonic_presentation_time():
    frames = parse_ffprobe_frames(probe_payload())
    assert len(frames) == 4
    assert frames[0].key_frame
    assert frames[-1].best_effort_timestamp_time == 0.13

    with pytest.raises(MediaWorkerError, match="Non-monotonic"):
        parse_ffprobe_frames(probe_payload((0.0, 0.04, 0.03)))


def test_media_processing_writes_verified_artifacts_and_is_idempotent(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original-video-evidence")
    work = tmp_path / "work"
    runner = FakeRunner()

    manifest = process_media(source, work_root=work, runner=runner, now=NOW)
    directory = work / manifest.processing_id
    assert manifest.schema == "ai.wagvid.media-processing.v1"
    assert manifest.source.sha256 == __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    assert manifest.proxy.source_sha256 == manifest.source.sha256
    assert manifest.proxy.output_size_bytes == len(b"synthetic-proxy-bytes")
    assert (directory / "frame-timeline.json").is_file()
    assert (directory / "review-proxy.mp4").is_file()
    assert (directory / "manifest.json").is_file()
    assert not (directory / "review-proxy.partial.mp4").exists()

    timeline = json.loads((directory / "frame-timeline.json").read_text())
    assert timeline["source_sha256"] == manifest.source.sha256
    assert timeline["frame_count"] == 4
    assert timeline["variable_frame_rate_observed"] is True
    stages = [record["stage"] for record in read_journal(directory / "journal.jsonl")]
    assert stages == [
        "planned",
        "probing",
        "timeline-written",
        "normalizing",
        "proxy-written",
        "verified",
    ]

    call_count = len(runner.calls)
    repeated = process_media(source, work_root=work, runner=runner, now=NOW)
    assert repeated == manifest
    assert len(runner.calls) == call_count


def test_failed_ffmpeg_never_publishes_proxy_or_verified_manifest(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    work = tmp_path / "work"
    runner = FakeRunner(fail_ffmpeg=True)

    with pytest.raises(MediaWorkerError, match="ffmpeg proxy failed"):
        process_media(source, work_root=work, runner=runner, now=NOW)

    directories = list(work.iterdir())
    assert len(directories) == 1
    directory = directories[0]
    assert not (directory / "manifest.json").exists()
    assert not (directory / "review-proxy.mp4").exists()
    assert read_journal(directory / "journal.jsonl")[-1]["stage"] == "failed"


def test_corrupted_verified_proxy_is_not_silently_reprocessed(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    work = tmp_path / "work"
    runner = FakeRunner()
    manifest = process_media(source, work_root=work, runner=runner, now=NOW)
    proxy = work / manifest.processing_id / manifest.proxy.relative_path
    proxy.write_bytes(b"tampered")

    with pytest.raises(MediaWorkerError, match="integrity check"):
        process_media(source, work_root=work, runner=runner, now=NOW)


def test_profile_change_gets_distinct_content_addressed_processing_directory(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    runner = FakeRunner()
    first = process_media(source, work_root=tmp_path / "work", runner=runner, now=NOW)
    second = process_media(
        source,
        work_root=tmp_path / "work",
        runner=runner,
        profile=ProxyProfile(profile_id="review-h264-vfr-crf20", crf=20),
        now=NOW,
    )
    assert first.processing_id != second.processing_id
    assert first.proxy.profile_digest != second.proxy.profile_digest


def test_incomplete_directory_requires_explicit_recovery_instead_of_overwriting(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    work = tmp_path / "work"
    failing = FakeRunner(fail_ffmpeg=True)
    with pytest.raises(MediaWorkerError):
        process_media(source, work_root=work, runner=failing, now=NOW)

    with pytest.raises(MediaWorkerError, match="explicit recovery"):
        process_media(source, work_root=work, runner=FakeRunner(), now=NOW)


def test_journal_detects_tampering_and_rejects_invalid_transition(tmp_path):
    journal = tmp_path / "journal.jsonl"
    append_journal(
        journal,
        processing_id_value="a" * 32,
        stage=MediaStage.PLANNED,
        occurred_at=NOW,
    )
    with pytest.raises(MediaWorkerError, match="Invalid media stage transition"):
        append_journal(
            journal,
            processing_id_value="a" * 32,
            stage=MediaStage.VERIFIED,
            occurred_at=NOW,
        )

    first = json.loads(journal.read_text().splitlines()[0])
    first["details"] = {"tampered": True}
    journal.write_text(json.dumps(first) + "\n")
    with pytest.raises(MediaWorkerError, match="hash mismatch"):
        read_journal(journal)
