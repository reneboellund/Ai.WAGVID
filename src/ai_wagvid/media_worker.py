"""Durable, VFR-safe media preparation for Ai.WAGVID workers.

The worker is deliberately independent of Django and object-storage SDKs. It accepts a
local source path that has already been staged by the ingest layer, produces a raw
FFprobe frame artifact plus a review proxy, and records an append-only hash-chained
journal. Tests inject a fake command runner; ordinary CI never transcodes video.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol, Sequence


class MediaWorkerError(RuntimeError):
    pass


class MediaStage(StrEnum):
    PLANNED = "planned"
    PROBING = "probing"
    TIMELINE_WRITTEN = "timeline-written"
    NORMALIZING = "normalizing"
    PROXY_WRITTEN = "proxy-written"
    VERIFIED = "verified"
    FAILED = "failed"


_ALLOWED_TRANSITIONS = {
    MediaStage.PLANNED: frozenset({MediaStage.PROBING, MediaStage.FAILED}),
    MediaStage.PROBING: frozenset({MediaStage.TIMELINE_WRITTEN, MediaStage.FAILED}),
    MediaStage.TIMELINE_WRITTEN: frozenset({MediaStage.NORMALIZING, MediaStage.FAILED}),
    MediaStage.NORMALIZING: frozenset({MediaStage.PROXY_WRITTEN, MediaStage.FAILED}),
    MediaStage.PROXY_WRITTEN: frozenset({MediaStage.VERIFIED, MediaStage.FAILED}),
    MediaStage.VERIFIED: frozenset(),
    MediaStage.FAILED: frozenset(),
}


@dataclass(frozen=True)
class SourceIdentity:
    sha256: str
    size_bytes: int
    original_name: str

    def __post_init__(self) -> None:
        if not self.sha256 or len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("source sha256 must be lowercase hexadecimal")
        if self.size_bytes < 0:
            raise ValueError("source size cannot be negative")
        if not self.original_name:
            raise ValueError("original_name is required")


@dataclass(frozen=True)
class ProxyProfile:
    profile_id: str = "review-h264-vfr-v1"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    movflags: str = "+faststart"

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        if not 0 <= self.crf <= 51:
            raise ValueError("CRF must be between 0 and 51")

    @property
    def digest(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FrameRecord:
    index: int
    best_effort_timestamp_time: float
    pts_time: float | None
    pkt_duration_time: float | None
    key_frame: bool


@dataclass(frozen=True)
class ProbeArtifact:
    schema: str
    source_sha256: str
    source_size_bytes: int
    created_at: str
    ffprobe_version: str
    command_digest: str
    raw_payload_sha256: str
    frame_count: int
    first_timestamp_seconds: float
    last_timestamp_seconds: float
    variable_frame_rate_observed: bool
    frames: tuple[FrameRecord, ...]


@dataclass(frozen=True)
class ProxyArtifact:
    profile_id: str
    profile_digest: str
    source_sha256: str
    output_sha256: str
    output_size_bytes: int
    ffmpeg_version: str
    command_digest: str
    relative_path: str


@dataclass(frozen=True)
class ProcessingManifest:
    schema: str
    processing_id: str
    source: SourceIdentity
    proxy_profile: ProxyProfile
    probe_artifact: str
    probe_artifact_sha256: str
    proxy: ProxyArtifact
    verified_at: str


@dataclass(frozen=True)
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], *, timeout_seconds: int) -> CommandResult: ...


@dataclass(frozen=True)
class WorkerTools:
    ffprobe: str = "ffprobe"
    ffmpeg: str = "ffmpeg"
    timeout_seconds: int = 900

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1 or self.timeout_seconds > 86_400:
            raise ValueError("tool timeout must be between 1 second and 24 hours")
        for binary in (self.ffprobe, self.ffmpeg):
            if not binary or any(ch in binary for ch in ("\n", "\r", "\x00")):
                raise ValueError("invalid tool binary name")


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def inspect_source(path: Path) -> SourceIdentity:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest, size = sha256_file(path)
    return SourceIdentity(digest, size, path.name)


def _command_digest(argv: Sequence[str]) -> str:
    # NUL separation hashes argv unambiguously without using a shell-escaped rendering.
    return hashlib.sha256("\x00".join(argv).encode()).hexdigest()


def format_command_for_audit(argv: Sequence[str]) -> str:
    """Human-only rendering. Execution always receives argv directly and never a shell string."""
    return " ".join(shlex.quote(item) for item in argv)


def ffprobe_version_command(tools: WorkerTools) -> list[str]:
    return [tools.ffprobe, "-version"]


def ffmpeg_version_command(tools: WorkerTools) -> list[str]:
    return [tools.ffmpeg, "-version"]


def ffprobe_frames_command(tools: WorkerTools, source: Path) -> list[str]:
    return [
        tools.ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries",
        "frame=best_effort_timestamp_time,pts_time,pkt_duration_time,key_frame",
        "-of", "json",
        str(source),
    ]


def ffmpeg_proxy_command(
    tools: WorkerTools,
    source: Path,
    output_partial: Path,
    profile: ProxyProfile,
) -> list[str]:
    # copyts + start_at_zero + fps_mode passthrough preserve source presentation timing/VFR.
    # There is intentionally no -r/fps filter in this command.
    return [
        tools.ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        "-n",
        "-copyts",
        "-start_at_zero",
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", profile.video_codec,
        "-crf", str(profile.crf),
        "-preset", profile.preset,
        "-pix_fmt", profile.pixel_format,
        "-fps_mode", "passthrough",
        "-c:a", profile.audio_codec,
        "-movflags", profile.movflags,
        str(output_partial),
    ]


def _version_line(output: str, tool: str) -> str:
    line = next((item.strip() for item in output.splitlines() if item.strip()), "")
    if not line:
        raise MediaWorkerError(f"{tool} did not report a version")
    return line[:300]


def _run_checked(
    runner: CommandRunner,
    argv: Sequence[str],
    *,
    timeout_seconds: int,
    label: str,
) -> CommandResult:
    result = runner.run(tuple(argv), timeout_seconds=timeout_seconds)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")[:500]
        raise MediaWorkerError(f"{label} failed with exit {result.returncode}: {detail}")
    return result


def _float_or_none(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value))
    except ValueError as error:
        raise MediaWorkerError(f"Invalid FFprobe timestamp value: {value!r}") from error


def parse_ffprobe_frames(payload: str) -> tuple[FrameRecord, ...]:
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as error:
        raise MediaWorkerError("FFprobe returned invalid JSON") from error
    raw_frames = decoded.get("frames") if isinstance(decoded, Mapping) else None
    if not isinstance(raw_frames, list) or not raw_frames:
        raise MediaWorkerError("FFprobe returned no video frames")

    frames: list[FrameRecord] = []
    previous = float("-inf")
    for index, raw in enumerate(raw_frames):
        if not isinstance(raw, Mapping):
            raise MediaWorkerError(f"FFprobe frame {index} is not an object")
        best = _float_or_none(raw.get("best_effort_timestamp_time"))
        if best is None:
            raise MediaWorkerError(f"FFprobe frame {index} lacks best-effort presentation time")
        if best < previous:
            raise MediaWorkerError(
                f"Non-monotonic presentation timeline at frame {index}: {best} < {previous}"
            )
        previous = best
        frames.append(
            FrameRecord(
                index=index,
                best_effort_timestamp_time=best,
                pts_time=_float_or_none(raw.get("pts_time")),
                pkt_duration_time=_float_or_none(raw.get("pkt_duration_time")),
                key_frame=str(raw.get("key_frame", "0")) in {"1", "true", "True"},
            )
        )
    return tuple(frames)


def _vfr_observed(frames: tuple[FrameRecord, ...]) -> bool:
    if len(frames) < 4:
        return False
    deltas = [
        round(frames[index].best_effort_timestamp_time - frames[index - 1].best_effort_timestamp_time, 6)
        for index in range(1, len(frames))
        if frames[index].best_effort_timestamp_time > frames[index - 1].best_effort_timestamp_time
    ]
    return len(set(deltas)) > 1


def write_atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with temporary.open("wb") as target:
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def _safe_processing_root(root: Path, processing_id: str) -> Path:
    if not processing_id or not all(char in "0123456789abcdef" for char in processing_id):
        raise ValueError("processing_id must be lowercase hexadecimal")
    base = root.resolve()
    path = (base / processing_id).resolve()
    if path.parent != base:
        raise ValueError("processing directory escapes worker root")
    return path


def processing_id(source: SourceIdentity, profile: ProxyProfile) -> str:
    seed = f"{source.sha256}:{source.size_bytes}:{profile.digest}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _journal_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_journal(path: Path) -> tuple[dict, ...]:
    if not path.exists():
        return ()
    records: list[dict] = []
    previous = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise MediaWorkerError(f"Invalid media journal JSON at line {line_number}") from error
        event_hash = record.pop("event_hash", None)
        if record.get("previous_hash") != previous:
            raise MediaWorkerError(f"Media journal hash chain broken at line {line_number}")
        calculated = _journal_hash(record)
        if event_hash != calculated:
            raise MediaWorkerError(f"Media journal event hash mismatch at line {line_number}")
        record["event_hash"] = event_hash
        records.append(record)
        previous = event_hash
    return tuple(records)


def append_journal(
    path: Path,
    *,
    processing_id_value: str,
    stage: MediaStage,
    occurred_at: datetime,
    details: Mapping[str, object] | None = None,
) -> str:
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("journal timestamp must be timezone-aware")
    records = read_journal(path)
    same = [item for item in records if item.get("processing_id") == processing_id_value]
    if not same:
        if stage != MediaStage.PLANNED:
            raise MediaWorkerError("First media journal stage must be planned")
    else:
        current = MediaStage(str(same[-1]["stage"]))
        if stage not in _ALLOWED_TRANSITIONS[current]:
            raise MediaWorkerError(f"Invalid media stage transition {current.value}->{stage.value}")
    previous = records[-1]["event_hash"] if records else None
    payload = {
        "processing_id": processing_id_value,
        "stage": stage.value,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "details": dict(details or {}),
        "previous_hash": previous,
    }
    event_hash = _journal_hash(payload)
    record = dict(payload)
    record["event_hash"] = event_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event_hash


def _probe_to_json(artifact: ProbeArtifact) -> dict:
    return {
        "schema": artifact.schema,
        "source_sha256": artifact.source_sha256,
        "source_size_bytes": artifact.source_size_bytes,
        "created_at": artifact.created_at,
        "ffprobe_version": artifact.ffprobe_version,
        "command_digest": artifact.command_digest,
        "raw_payload_sha256": artifact.raw_payload_sha256,
        "frame_count": artifact.frame_count,
        "first_timestamp_seconds": artifact.first_timestamp_seconds,
        "last_timestamp_seconds": artifact.last_timestamp_seconds,
        "variable_frame_rate_observed": artifact.variable_frame_rate_observed,
        "frames": [asdict(frame) for frame in artifact.frames],
    }


def _manifest_to_json(manifest: ProcessingManifest) -> dict:
    return {
        "schema": manifest.schema,
        "processing_id": manifest.processing_id,
        "source": asdict(manifest.source),
        "proxy_profile": asdict(manifest.proxy_profile),
        "probe_artifact": manifest.probe_artifact,
        "probe_artifact_sha256": manifest.probe_artifact_sha256,
        "proxy": asdict(manifest.proxy),
        "verified_at": manifest.verified_at,
    }


def load_verified_manifest(path: Path) -> ProcessingManifest | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        source = SourceIdentity(**value["source"])
        profile = ProxyProfile(**value["proxy_profile"])
        proxy = ProxyArtifact(**value["proxy"])
        return ProcessingManifest(
            schema=value["schema"],
            processing_id=value["processing_id"],
            source=source,
            proxy_profile=profile,
            probe_artifact=value["probe_artifact"],
            probe_artifact_sha256=value["probe_artifact_sha256"],
            proxy=proxy,
            verified_at=value["verified_at"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MediaWorkerError("Existing processing manifest is invalid") from error


def verify_existing_manifest(directory: Path, manifest: ProcessingManifest) -> bool:
    if manifest.schema != "ai.wagvid.media-processing.v1":
        return False
    probe_path = directory / manifest.probe_artifact
    proxy_path = directory / manifest.proxy.relative_path
    if not probe_path.is_file() or not proxy_path.is_file():
        return False
    probe_hash, _ = sha256_file(probe_path)
    proxy_hash, proxy_size = sha256_file(proxy_path)
    return (
        probe_hash == manifest.probe_artifact_sha256
        and proxy_hash == manifest.proxy.output_sha256
        and proxy_size == manifest.proxy.output_size_bytes
    )


def process_media(
    source_path: Path,
    *,
    work_root: Path,
    runner: CommandRunner,
    tools: WorkerTools = WorkerTools(),
    profile: ProxyProfile = ProxyProfile(),
    now: datetime | None = None,
) -> ProcessingManifest:
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    source = inspect_source(source_path)
    pid = processing_id(source, profile)
    directory = _safe_processing_root(work_root, pid)
    manifest_path = directory / "manifest.json"
    existing = load_verified_manifest(manifest_path)
    if existing is not None:
        if existing.source != source or existing.proxy_profile.digest != profile.digest:
            raise MediaWorkerError("Existing processing manifest does not match source/profile")
        if not verify_existing_manifest(directory, existing):
            raise MediaWorkerError("Existing verified processing artifacts failed integrity check")
        return existing

    directory.mkdir(parents=True, exist_ok=True)
    journal = directory / "journal.jsonl"
    if journal.exists():
        raise MediaWorkerError("Incomplete media processing directory requires explicit recovery")

    append_journal(journal, processing_id_value=pid, stage=MediaStage.PLANNED, occurred_at=current,
                   details={"source_sha256": source.sha256, "profile_digest": profile.digest})
    try:
        ffprobe_version = _version_line(
            _run_checked(runner, ffprobe_version_command(tools), timeout_seconds=30, label="ffprobe version").stdout,
            "ffprobe",
        )
        ffmpeg_version = _version_line(
            _run_checked(runner, ffmpeg_version_command(tools), timeout_seconds=30, label="ffmpeg version").stdout,
            "ffmpeg",
        )
        append_journal(journal, processing_id_value=pid, stage=MediaStage.PROBING, occurred_at=current,
                       details={"ffprobe_version": ffprobe_version})
        probe_command = ffprobe_frames_command(tools, source_path)
        probe_result = _run_checked(
            runner, probe_command, timeout_seconds=tools.timeout_seconds, label="ffprobe frames"
        )
        frames = parse_ffprobe_frames(probe_result.stdout)
        raw_hash = hashlib.sha256(probe_result.stdout.encode()).hexdigest()
        probe = ProbeArtifact(
            schema="ai.wagvid.ffprobe-frame-timeline.v1",
            source_sha256=source.sha256,
            source_size_bytes=source.size_bytes,
            created_at=current.astimezone(UTC).isoformat(),
            ffprobe_version=ffprobe_version,
            command_digest=_command_digest(probe_command),
            raw_payload_sha256=raw_hash,
            frame_count=len(frames),
            first_timestamp_seconds=frames[0].best_effort_timestamp_time,
            last_timestamp_seconds=frames[-1].best_effort_timestamp_time,
            variable_frame_rate_observed=_vfr_observed(frames),
            frames=frames,
        )
        probe_path = directory / "frame-timeline.json"
        write_atomic_json(probe_path, _probe_to_json(probe))
        probe_hash, _ = sha256_file(probe_path)
        append_journal(journal, processing_id_value=pid, stage=MediaStage.TIMELINE_WRITTEN,
                       occurred_at=current, details={"frame_count": len(frames), "artifact_sha256": probe_hash})

        proxy_partial = directory / "review-proxy.partial.mp4"
        proxy_final = directory / "review-proxy.mp4"
        if proxy_partial.exists() or proxy_final.exists():
            raise MediaWorkerError("Proxy path already exists in incomplete processing directory")
        append_journal(journal, processing_id_value=pid, stage=MediaStage.NORMALIZING, occurred_at=current,
                       details={"profile_id": profile.profile_id, "ffmpeg_version": ffmpeg_version})
        proxy_command = ffmpeg_proxy_command(tools, source_path, proxy_partial, profile)
        _run_checked(runner, proxy_command, timeout_seconds=tools.timeout_seconds, label="ffmpeg proxy")
        if not proxy_partial.is_file():
            raise MediaWorkerError("FFmpeg reported success but proxy output is missing")
        proxy_hash, proxy_size = sha256_file(proxy_partial)
        if proxy_size <= 0:
            raise MediaWorkerError("FFmpeg proxy output is empty")
        os.replace(proxy_partial, proxy_final)
        proxy = ProxyArtifact(
            profile_id=profile.profile_id,
            profile_digest=profile.digest,
            source_sha256=source.sha256,
            output_sha256=proxy_hash,
            output_size_bytes=proxy_size,
            ffmpeg_version=ffmpeg_version,
            command_digest=_command_digest(proxy_command),
            relative_path=proxy_final.name,
        )
        append_journal(journal, processing_id_value=pid, stage=MediaStage.PROXY_WRITTEN,
                       occurred_at=current, details={"output_sha256": proxy_hash, "output_size_bytes": proxy_size})
        manifest = ProcessingManifest(
            schema="ai.wagvid.media-processing.v1",
            processing_id=pid,
            source=source,
            proxy_profile=profile,
            probe_artifact=probe_path.name,
            probe_artifact_sha256=probe_hash,
            proxy=proxy,
            verified_at=current.astimezone(UTC).isoformat(),
        )
        write_atomic_json(manifest_path, _manifest_to_json(manifest))
        append_journal(journal, processing_id_value=pid, stage=MediaStage.VERIFIED, occurred_at=current,
                       details={"manifest_sha256": sha256_file(manifest_path)[0]})
        return manifest
    except Exception as error:
        records = read_journal(journal)
        if records and MediaStage(str(records[-1]["stage"])) not in {MediaStage.FAILED, MediaStage.VERIFIED}:
            append_journal(
                journal,
                processing_id_value=pid,
                stage=MediaStage.FAILED,
                occurred_at=current,
                details={"error_type": type(error).__name__, "error": str(error)[:500]},
            )
        raise
