"""Immutable persistence for canonical frame timelines derived from verified source media."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from fractions import Fraction
from io import BytesIO
from typing import Any, Mapping

from ai_wagvid.media_timeline import (
    CanonicalTimeline,
    FrameTimestamp,
    build_timeline,
    parse_ffprobe_frames,
)

from .models import MediaAsset
from .storage import LocalObjectStore, ObjectIntegrityError

TIMELINE_SCHEMA_VERSION = "canonical-media-timeline-v1"
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024


def timeline_object_key(media: MediaAsset) -> str:
    if not media.sha256 or len(media.sha256) != 64:
        raise ValueError("media must have a complete source SHA-256")
    return (
        f"organizations/{media.organization_id}/derived/media/{media.id}/"
        f"{media.sha256}/{TIMELINE_SCHEMA_VERSION}.json"
    )


def timeline_manifest(timeline: CanonicalTimeline) -> dict[str, Any]:
    return {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "source_sha256": timeline.source_sha256,
        "stream_index": timeline.stream_index,
        "time_base": {
            "numerator": timeline.time_base.numerator,
            "denominator": timeline.time_base.denominator,
        },
        "timeline_digest": timeline.digest,
        "diagnostics": asdict(timeline.diagnostics),
        "frames": [asdict(frame) for frame in timeline.frames],
    }


def timeline_manifest_bytes(timeline: CanonicalTimeline) -> bytes:
    return json.dumps(
        timeline_manifest(timeline), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def timeline_from_manifest(payload: str | bytes | Mapping[str, Any]) -> CanonicalTimeline:
    if isinstance(payload, bytes):
        data = json.loads(payload.decode("utf-8"))
    elif isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = dict(payload)
    if data.get("schema_version") != TIMELINE_SCHEMA_VERSION:
        raise ValueError("unsupported canonical timeline schema")
    time_base_data = data.get("time_base") or {}
    try:
        time_base = Fraction(
            int(time_base_data["numerator"]), int(time_base_data["denominator"])
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError("timeline manifest has invalid time_base") from error
    frames = tuple(
        FrameTimestamp(
            frame_index=int(item["frame_index"]),
            pts=int(item["pts"]) if item.get("pts") is not None else None,
            dts=int(item["dts"]) if item.get("dts") is not None else None,
            best_effort_timestamp=int(item["best_effort_timestamp"]),
            duration_ticks=(
                int(item["duration_ticks"])
                if item.get("duration_ticks") is not None
                else None
            ),
            key_frame=bool(item.get("key_frame", False)),
        )
        for item in data.get("frames") or []
    )
    timeline = build_timeline(
        source_sha256=str(data.get("source_sha256") or ""),
        time_base=time_base,
        frames=frames,
        stream_index=int(data.get("stream_index", 0)),
    )
    if data.get("timeline_digest") != timeline.digest:
        raise ObjectIntegrityError("canonical timeline digest mismatch")
    expected_diagnostics = data.get("diagnostics") or {}
    actual_diagnostics = asdict(timeline.diagnostics)
    for field, value in actual_diagnostics.items():
        stored = expected_diagnostics.get(field)
        if isinstance(value, tuple):
            value = list(value)
        if stored != value:
            raise ObjectIntegrityError(f"canonical timeline diagnostics mismatch: {field}")
    return timeline


def persist_media_timeline(
    media: MediaAsset,
    ffprobe_payload: str | Mapping[str, Any],
    *,
    store: LocalObjectStore | None = None,
    stream_index: int = 0,
) -> CanonicalTimeline:
    if media.state != MediaAsset.State.STORED:
        raise ValueError("canonical timeline requires verified stored media")
    if len(media.sha256) != 64:
        raise ValueError("canonical timeline requires source SHA-256")
    timeline = parse_ffprobe_frames(
        ffprobe_payload, source_sha256=media.sha256, stream_index=stream_index
    )
    content = timeline_manifest_bytes(timeline)
    digest = hashlib.sha256(content).hexdigest()
    (store or LocalObjectStore()).put_verified(
        timeline_object_key(media),
        BytesIO(content),
        expected_size=len(content),
        expected_sha256=digest,
    )
    return timeline


def load_media_timeline(
    media: MediaAsset, *, store: LocalObjectStore | None = None
) -> CanonicalTimeline:
    object_store = store or LocalObjectStore()
    key = timeline_object_key(media)
    stored = object_store.inspect(key)
    if stored.size > _MAX_MANIFEST_BYTES:
        raise ObjectIntegrityError("canonical timeline manifest exceeds safety limit")
    with object_store.open_read(key) as source:
        content = source.read(_MAX_MANIFEST_BYTES + 1)
    if len(content) != stored.size:
        raise ObjectIntegrityError("canonical timeline manifest size changed during read")
    timeline = timeline_from_manifest(content)
    if timeline.source_sha256 != media.sha256:
        raise ObjectIntegrityError("canonical timeline belongs to a different source")
    return timeline


def timeline_exists(media: MediaAsset, *, store: LocalObjectStore | None = None) -> bool:
    try:
        return (store or LocalObjectStore()).exists(timeline_object_key(media))
    except ValueError:
        return False
