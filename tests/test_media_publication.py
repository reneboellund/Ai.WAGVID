from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_wagvid.media_publication import (
    ProxyPersistenceReceipt,
    RemoteArtifactReceipt,
    TimelinePersistenceReceipt,
    load_publication_receipt,
    publish_processing_set,
)
from ai_wagvid.media_worker import CommandResult, MediaWorkerError, process_media


NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)


class ProcessingRunner:
    def run(self, argv, *, timeout_seconds):
        executable = Path(argv[0]).name
        if len(argv) == 2 and argv[1] == "-version":
            return CommandResult(stdout=f"{executable} version test\n")
        if "ffprobe" in executable:
            return CommandResult(
                stdout='{"frames":['
                '{"best_effort_timestamp_time":"0.000000","pts_time":"0.000000","pkt_duration_time":"0.040000","key_frame":1},'
                '{"best_effort_timestamp_time":"0.041000","pts_time":"0.041000","pkt_duration_time":"0.041000","key_frame":0}]}'
            )
        Path(argv[-1]).write_bytes(b"review-proxy")
        return CommandResult()


class FakeStore:
    provider_id = "derived-store"

    def __init__(self, *, wrong_hash=False):
        self.calls = []
        self.wrong_hash = wrong_hash
        self.by_idempotency = {}

    def put_verified_file(
        self, *, key, local_path, expected_sha256, expected_size, metadata, idempotency_key
    ):
        self.calls.append((key, dict(metadata), idempotency_key))
        existing = self.by_idempotency.get(idempotency_key)
        if existing is not None:
            return existing
        receipt = RemoteArtifactReceipt(
            self.provider_id,
            key,
            "0" * 64 if self.wrong_hash else expected_sha256,
            expected_size,
            version_id="v1",
        )
        self.by_idempotency[idempotency_key] = receipt
        return receipt


class FakeSink:
    def __init__(self, *, fail_proxy_once=False):
        self.timeline_calls = []
        self.proxy_calls = []
        self.fail_proxy_once = fail_proxy_once
        self.timeline_by_key = {}
        self.proxy_by_key = {}

    def persist_timeline(
        self, *, source_sha256, processing_id, artifact_sha256, ffprobe_payload,
        remote_artifact, idempotency_key
    ):
        self.timeline_calls.append((idempotency_key, ffprobe_payload, remote_artifact))
        if idempotency_key not in self.timeline_by_key:
            self.timeline_by_key[idempotency_key] = TimelinePersistenceReceipt(
                "timeline-1", source_sha256, artifact_sha256
            )
        return self.timeline_by_key[idempotency_key]

    def persist_proxy(
        self, *, source_sha256, processing_id, profile_id, profile_digest, artifact_sha256,
        size_bytes, remote_artifact, idempotency_key
    ):
        self.proxy_calls.append((idempotency_key, remote_artifact))
        if self.fail_proxy_once:
            self.fail_proxy_once = False
            raise RuntimeError("synthetic database outage")
        if idempotency_key not in self.proxy_by_key:
            self.proxy_by_key[idempotency_key] = ProxyPersistenceReceipt(
                "proxy-1", source_sha256, artifact_sha256
            )
        return self.proxy_by_key[idempotency_key]


def processing_directory(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"immutable-original")
    manifest = process_media(
        source,
        work_root=tmp_path / "work",
        runner=ProcessingRunner(),
        now=NOW,
    )
    return source, tmp_path / "work" / manifest.processing_id


def test_verified_set_publishes_only_derived_content_addressed_artifacts_then_persists(tmp_path):
    source, directory = processing_directory(tmp_path)
    original = source.read_bytes()
    store = FakeStore()
    sink = FakeSink()

    receipt = publish_processing_set(directory, store=store, sink=sink)
    assert receipt.schema == "ai.wagvid.media-publication.v1"
    assert len(store.calls) == 3
    assert len(sink.timeline_calls) == 1
    assert len(sink.proxy_calls) == 1
    assert all(key.startswith(f"derived/{receipt.source_sha256}/{receipt.processing_id}/") for key, _, _ in store.calls)
    assert all("original" not in key for key, _, _ in store.calls)
    assert source.read_bytes() == original
    assert (directory / "publication.json").is_file()

    timeline_payload = sink.timeline_calls[0][1]
    assert timeline_payload["frames"][1]["best_effort_timestamp_time"] == "0.041000000"


def test_local_publication_receipt_makes_repeat_a_noop(tmp_path):
    _, directory = processing_directory(tmp_path)
    store = FakeStore()
    sink = FakeSink()
    first = publish_processing_set(directory, store=store, sink=sink)
    counts = (len(store.calls), len(sink.timeline_calls), len(sink.proxy_calls))
    second = publish_processing_set(directory, store=store, sink=sink)
    assert second == first
    assert (len(store.calls), len(sink.timeline_calls), len(sink.proxy_calls)) == counts


def test_remote_hash_mismatch_blocks_application_persistence(tmp_path):
    _, directory = processing_directory(tmp_path)
    store = FakeStore(wrong_hash=True)
    sink = FakeSink()
    with pytest.raises(MediaWorkerError, match="remote SHA-256 mismatch"):
        publish_processing_set(directory, store=store, sink=sink)
    assert sink.timeline_calls == []
    assert sink.proxy_calls == []
    assert not (directory / "publication.json").exists()


def test_sink_failure_is_retryable_with_same_remote_and_sink_idempotency_keys(tmp_path):
    _, directory = processing_directory(tmp_path)
    store = FakeStore()
    sink = FakeSink(fail_proxy_once=True)
    with pytest.raises(RuntimeError, match="database outage"):
        publish_processing_set(directory, store=store, sink=sink)
    assert not (directory / "publication.json").exists()
    first_store_keys = [call[2] for call in store.calls]
    first_timeline_key = sink.timeline_calls[0][0]

    receipt = publish_processing_set(directory, store=store, sink=sink)
    assert receipt.proxy_persistence.proxy_id == "proxy-1"
    assert [call[2] for call in store.calls[:3]] == first_store_keys
    assert [call[2] for call in store.calls[3:]] == first_store_keys
    assert sink.timeline_calls[1][0] == first_timeline_key
    assert len(store.by_idempotency) == 3
    assert len(sink.timeline_by_key) == 1
    assert len(sink.proxy_by_key) == 1


def test_tampered_publication_receipt_is_detected(tmp_path):
    _, directory = processing_directory(tmp_path)
    receipt = publish_processing_set(directory, store=FakeStore(), sink=FakeSink())
    path = directory / "publication.json"
    path.write_text(path.read_text().replace(receipt.provider_id, "other-provider", 1))
    with pytest.raises(MediaWorkerError, match="digest mismatch"):
        load_publication_receipt(path)
