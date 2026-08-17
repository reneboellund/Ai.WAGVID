"""Operator-safe recovery for interrupted/failed media worker directories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .media_worker import MediaStage, MediaWorkerError, read_journal


@dataclass(frozen=True)
class FailedProcessingSet:
    processing_id: str
    source_directory: Path
    last_stage: MediaStage
    journal_events: int
    has_timeline: bool
    has_partial_proxy: bool
    has_proxy: bool
    has_manifest: bool


def _safe_child(root: Path, name: str) -> Path:
    if not name or not all(character in "0123456789abcdef" for character in name):
        raise ValueError("processing_id must be lowercase hexadecimal")
    base = root.resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise ValueError("processing directory escapes root")
    return path


def inspect_failed_processing(work_root: Path, processing_id: str) -> FailedProcessingSet:
    directory = _safe_child(work_root, processing_id)
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    journal_path = directory / "journal.jsonl"
    records = read_journal(journal_path)
    if not records:
        raise MediaWorkerError("Processing directory has no valid journal")
    last_stage = MediaStage(str(records[-1]["stage"]))
    if last_stage == MediaStage.VERIFIED:
        raise MediaWorkerError("Verified processing set cannot enter failed-set recovery")
    if last_stage != MediaStage.FAILED:
        raise MediaWorkerError(
            f"Processing set is not terminally failed; last stage is {last_stage.value}"
        )
    return FailedProcessingSet(
        processing_id=processing_id,
        source_directory=directory,
        last_stage=last_stage,
        journal_events=len(records),
        has_timeline=(directory / "frame-timeline.json").is_file(),
        has_partial_proxy=(directory / "review-proxy.partial.mp4").is_file(),
        has_proxy=(directory / "review-proxy.mp4").is_file(),
        has_manifest=(directory / "manifest.json").is_file(),
    )


def quarantine_failed_processing(
    work_root: Path,
    processing_id: str,
    *,
    quarantine_root: Path,
    now: datetime | None = None,
) -> Path:
    """Atomically move a failed set aside without deleting any forensic artifacts."""
    failed = inspect_failed_processing(work_root, processing_id)
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    target_root = quarantine_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    timestamp = current.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    target = (target_root / f"{processing_id}-{timestamp}").resolve()
    if target.parent != target_root:
        raise ValueError("quarantine target escapes quarantine root")
    if target.exists():
        raise FileExistsError(target)
    os.replace(failed.source_directory, target)
    return target
