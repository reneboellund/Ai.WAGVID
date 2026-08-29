from datetime import UTC, datetime

import pytest

from ai_wagvid.media_worker import CommandResult, MediaWorkerError, process_media
from ai_wagvid.media_worker_recovery import (
    inspect_failed_processing,
    quarantine_failed_processing,
)

NOW = datetime(2026, 8, 17, 9, 45, tzinfo=UTC)


class FailingRunner:
    def run(self, argv, *, timeout_seconds):
        executable = argv[0]
        if len(argv) == 2 and argv[1] == "-version":
            return CommandResult(stdout=f"{executable} version test\n")
        if "ffprobe" in executable:
            return CommandResult(
                stdout='{"frames":[{"best_effort_timestamp_time":"0.000000","pts_time":"0.000000","pkt_duration_time":"0.040000","key_frame":1}]}'
            )
        return CommandResult(stderr="synthetic failure", returncode=3)


class SuccessRunner:
    def run(self, argv, *, timeout_seconds):
        executable = argv[0]
        if len(argv) == 2 and argv[1] == "-version":
            return CommandResult(stdout=f"{executable} version test\n")
        if "ffprobe" in executable:
            return CommandResult(
                stdout='{"frames":[{"best_effort_timestamp_time":"0.000000","pts_time":"0.000000","pkt_duration_time":"0.040000","key_frame":1}]}'
            )
        from pathlib import Path

        Path(argv[-1]).write_bytes(b"proxy")
        return CommandResult()


def test_failed_set_can_be_quarantined_without_deleting_evidence_and_retried(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    with pytest.raises(MediaWorkerError):
        process_media(source, work_root=work, runner=FailingRunner(), now=NOW)

    directory = next(work.iterdir())
    processing_id = directory.name
    failed = inspect_failed_processing(work, processing_id)
    assert failed.last_stage.value == "failed"
    assert failed.has_timeline
    assert failed.journal_events >= 4

    quarantine = quarantine_failed_processing(
        work,
        processing_id,
        quarantine_root=tmp_path / "quarantine",
        now=NOW,
    )
    assert quarantine.is_dir()
    assert (quarantine / "journal.jsonl").is_file()
    assert (quarantine / "frame-timeline.json").is_file()
    assert not directory.exists()

    retried = process_media(source, work_root=work, runner=SuccessRunner(), now=NOW)
    assert retried.processing_id == processing_id
    assert (work / processing_id / "manifest.json").is_file()


def test_verified_set_cannot_be_quarantined_as_failed(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    manifest = process_media(source, work_root=work, runner=SuccessRunner(), now=NOW)
    with pytest.raises(MediaWorkerError, match="Verified"):
        quarantine_failed_processing(
            work,
            manifest.processing_id,
            quarantine_root=tmp_path / "quarantine",
            now=NOW,
        )


def test_tampered_failed_journal_blocks_quarantine(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    work = tmp_path / "work"
    with pytest.raises(MediaWorkerError):
        process_media(source, work_root=work, runner=FailingRunner(), now=NOW)
    directory = next(work.iterdir())
    journal = directory / "journal.jsonl"
    journal.write_text(journal.read_text().replace("synthetic failure", "different failure"))
    with pytest.raises(MediaWorkerError, match="hash mismatch"):
        quarantine_failed_processing(
            work,
            directory.name,
            quarantine_root=tmp_path / "quarantine",
            now=NOW,
        )
