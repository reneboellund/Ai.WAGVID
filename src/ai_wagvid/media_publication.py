"""Verified publication of local media-worker artifacts to application/storage boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .media_timeline_handoff import ffprobe_import_payload, load_worker_timeline
from .media_worker import (
    MediaWorkerError,
    ProcessingManifest,
    load_verified_manifest,
    sha256_file,
    verify_existing_manifest,
    write_atomic_json,
)


@dataclass(frozen=True)
class RemoteArtifactReceipt:
    provider_id: str
    key: str
    sha256: str
    size_bytes: int
    version_id: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id or not self.key:
            raise ValueError("provider_id and key are required")
        if len(self.sha256) != 64:
            raise ValueError("remote artifact sha256 is invalid")
        if self.size_bytes < 0:
            raise ValueError("remote artifact size cannot be negative")


class DerivedArtifactStore(Protocol):
    provider_id: str

    def put_verified_file(
        self,
        *,
        key: str,
        local_path: Path,
        expected_sha256: str,
        expected_size: int,
        metadata: Mapping[str, str],
        idempotency_key: str,
    ) -> RemoteArtifactReceipt: ...


@dataclass(frozen=True)
class TimelinePersistenceReceipt:
    timeline_id: str
    source_sha256: str
    artifact_sha256: str


@dataclass(frozen=True)
class ProxyPersistenceReceipt:
    proxy_id: str
    source_sha256: str
    artifact_sha256: str


class ApplicationMediaSink(Protocol):
    def persist_timeline(
        self,
        *,
        source_sha256: str,
        processing_id: str,
        artifact_sha256: str,
        ffprobe_payload: Mapping[str, object],
        remote_artifact: RemoteArtifactReceipt,
        idempotency_key: str,
    ) -> TimelinePersistenceReceipt: ...

    def persist_proxy(
        self,
        *,
        source_sha256: str,
        processing_id: str,
        profile_id: str,
        profile_digest: str,
        artifact_sha256: str,
        size_bytes: int,
        remote_artifact: RemoteArtifactReceipt,
        idempotency_key: str,
    ) -> ProxyPersistenceReceipt: ...


@dataclass(frozen=True)
class PublicationReceipt:
    schema: str
    processing_id: str
    source_sha256: str
    provider_id: str
    timeline_remote: RemoteArtifactReceipt
    proxy_remote: RemoteArtifactReceipt
    manifest_remote: RemoteArtifactReceipt
    timeline_persistence: TimelinePersistenceReceipt
    proxy_persistence: ProxyPersistenceReceipt
    publication_digest: str


def _artifact_key(
    manifest: ProcessingManifest,
    *,
    kind: str,
    artifact_sha256: str,
    filename: str,
) -> str:
    if kind not in {"timeline", "proxy", "manifest"}:
        raise ValueError("unsupported derived artifact kind")
    safe_name = Path(filename).name
    if safe_name != filename or safe_name in {"", ".", ".."}:
        raise ValueError("unsafe artifact filename")
    return (
        f"derived/{manifest.source.sha256}/{manifest.processing_id}/"
        f"{kind}/{artifact_sha256}/{safe_name}"
    )


def _idempotency(processing_id: str, kind: str, artifact_sha256: str) -> str:
    digest = hashlib.sha256(f"{processing_id}:{kind}:{artifact_sha256}".encode()).hexdigest()
    return f"media-publication:{digest}"


def _validate_remote(
    receipt: RemoteArtifactReceipt,
    *,
    expected_provider: str,
    expected_key: str,
    expected_sha256: str,
    expected_size: int,
) -> None:
    if receipt.provider_id != expected_provider:
        raise MediaWorkerError("Derived artifact provider receipt mismatch")
    if receipt.key != expected_key:
        raise MediaWorkerError("Derived artifact remote key mismatch")
    if receipt.sha256 != expected_sha256:
        raise MediaWorkerError("Derived artifact remote SHA-256 mismatch")
    if receipt.size_bytes != expected_size:
        raise MediaWorkerError("Derived artifact remote size mismatch")


def _receipt_to_json(receipt: PublicationReceipt) -> dict:
    return {
        "schema": receipt.schema,
        "processing_id": receipt.processing_id,
        "source_sha256": receipt.source_sha256,
        "provider_id": receipt.provider_id,
        "timeline_remote": asdict(receipt.timeline_remote),
        "proxy_remote": asdict(receipt.proxy_remote),
        "manifest_remote": asdict(receipt.manifest_remote),
        "timeline_persistence": asdict(receipt.timeline_persistence),
        "proxy_persistence": asdict(receipt.proxy_persistence),
        "publication_digest": receipt.publication_digest,
    }


def _publication_digest(value: Mapping[str, object]) -> str:
    material = dict(value)
    material.pop("publication_digest", None)
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_publication_receipt(path: Path) -> PublicationReceipt | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        receipt = PublicationReceipt(
            schema=value["schema"],
            processing_id=value["processing_id"],
            source_sha256=value["source_sha256"],
            provider_id=value["provider_id"],
            timeline_remote=RemoteArtifactReceipt(**value["timeline_remote"]),
            proxy_remote=RemoteArtifactReceipt(**value["proxy_remote"]),
            manifest_remote=RemoteArtifactReceipt(**value["manifest_remote"]),
            timeline_persistence=TimelinePersistenceReceipt(**value["timeline_persistence"]),
            proxy_persistence=ProxyPersistenceReceipt(**value["proxy_persistence"]),
            publication_digest=value["publication_digest"],
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MediaWorkerError("Publication receipt is invalid") from error
    calculated = _publication_digest(_receipt_to_json(receipt))
    if calculated != receipt.publication_digest:
        raise MediaWorkerError("Publication receipt digest mismatch")
    return receipt


def publish_processing_set(
    processing_directory: Path,
    *,
    store: DerivedArtifactStore,
    sink: ApplicationMediaSink,
) -> PublicationReceipt:
    manifest_path = processing_directory / "manifest.json"
    manifest = load_verified_manifest(manifest_path)
    if manifest is None:
        raise MediaWorkerError("Verified processing manifest is missing")
    if processing_directory.name != manifest.processing_id:
        raise MediaWorkerError("Processing directory identity does not match manifest")
    if not verify_existing_manifest(processing_directory, manifest):
        raise MediaWorkerError("Local processing artifacts failed integrity verification")

    receipt_path = processing_directory / "publication.json"
    existing = load_publication_receipt(receipt_path)
    if existing is not None:
        if (
            existing.processing_id != manifest.processing_id
            or existing.source_sha256 != manifest.source.sha256
            or existing.provider_id != store.provider_id
        ):
            raise MediaWorkerError("Existing publication receipt does not match current target")
        return existing

    timeline_path = processing_directory / manifest.probe_artifact
    timeline_hash, timeline_size = sha256_file(timeline_path)
    if timeline_hash != manifest.probe_artifact_sha256:
        raise MediaWorkerError("Timeline changed after processing verification")
    timeline = load_worker_timeline(
        timeline_path,
        expected_source_sha256=manifest.source.sha256,
        expected_artifact_sha256=timeline_hash,
    )
    import_payload = ffprobe_import_payload(timeline)

    proxy_path = processing_directory / manifest.proxy.relative_path
    proxy_hash, proxy_size = sha256_file(proxy_path)
    if proxy_hash != manifest.proxy.output_sha256 or proxy_size != manifest.proxy.output_size_bytes:
        raise MediaWorkerError("Proxy changed after processing verification")
    manifest_hash, manifest_size = sha256_file(manifest_path)

    timeline_key = _artifact_key(
        manifest,
        kind="timeline",
        artifact_sha256=timeline_hash,
        filename=timeline_path.name,
    )
    proxy_key = _artifact_key(
        manifest,
        kind="proxy",
        artifact_sha256=proxy_hash,
        filename=proxy_path.name,
    )
    manifest_key = _artifact_key(
        manifest,
        kind="manifest",
        artifact_sha256=manifest_hash,
        filename=manifest_path.name,
    )
    common_metadata = {
        "source-sha256": manifest.source.sha256,
        "processing-id": manifest.processing_id,
        "derived": "true",
    }

    timeline_remote = store.put_verified_file(
        key=timeline_key,
        local_path=timeline_path,
        expected_sha256=timeline_hash,
        expected_size=timeline_size,
        metadata={**common_metadata, "artifact-kind": "timeline"},
        idempotency_key=_idempotency(manifest.processing_id, "timeline", timeline_hash),
    )
    _validate_remote(
        timeline_remote,
        expected_provider=store.provider_id,
        expected_key=timeline_key,
        expected_sha256=timeline_hash,
        expected_size=timeline_size,
    )

    proxy_remote = store.put_verified_file(
        key=proxy_key,
        local_path=proxy_path,
        expected_sha256=proxy_hash,
        expected_size=proxy_size,
        metadata={**common_metadata, "artifact-kind": "review-proxy", "profile-id": manifest.proxy.profile_id},
        idempotency_key=_idempotency(manifest.processing_id, "proxy", proxy_hash),
    )
    _validate_remote(
        proxy_remote,
        expected_provider=store.provider_id,
        expected_key=proxy_key,
        expected_sha256=proxy_hash,
        expected_size=proxy_size,
    )

    manifest_remote = store.put_verified_file(
        key=manifest_key,
        local_path=manifest_path,
        expected_sha256=manifest_hash,
        expected_size=manifest_size,
        metadata={**common_metadata, "artifact-kind": "processing-manifest"},
        idempotency_key=_idempotency(manifest.processing_id, "manifest", manifest_hash),
    )
    _validate_remote(
        manifest_remote,
        expected_provider=store.provider_id,
        expected_key=manifest_key,
        expected_sha256=manifest_hash,
        expected_size=manifest_size,
    )

    timeline_persistence = sink.persist_timeline(
        source_sha256=manifest.source.sha256,
        processing_id=manifest.processing_id,
        artifact_sha256=timeline_hash,
        ffprobe_payload=import_payload,
        remote_artifact=timeline_remote,
        idempotency_key=_idempotency(manifest.processing_id, "timeline-persist", timeline_hash),
    )
    if (
        timeline_persistence.source_sha256 != manifest.source.sha256
        or timeline_persistence.artifact_sha256 != timeline_hash
    ):
        raise MediaWorkerError("Timeline persistence receipt does not match published timeline")

    proxy_persistence = sink.persist_proxy(
        source_sha256=manifest.source.sha256,
        processing_id=manifest.processing_id,
        profile_id=manifest.proxy.profile_id,
        profile_digest=manifest.proxy.profile_digest,
        artifact_sha256=proxy_hash,
        size_bytes=proxy_size,
        remote_artifact=proxy_remote,
        idempotency_key=_idempotency(manifest.processing_id, "proxy-persist", proxy_hash),
    )
    if (
        proxy_persistence.source_sha256 != manifest.source.sha256
        or proxy_persistence.artifact_sha256 != proxy_hash
    ):
        raise MediaWorkerError("Proxy persistence receipt does not match published proxy")

    provisional = PublicationReceipt(
        schema="ai.wagvid.media-publication.v1",
        processing_id=manifest.processing_id,
        source_sha256=manifest.source.sha256,
        provider_id=store.provider_id,
        timeline_remote=timeline_remote,
        proxy_remote=proxy_remote,
        manifest_remote=manifest_remote,
        timeline_persistence=timeline_persistence,
        proxy_persistence=proxy_persistence,
        publication_digest="",
    )
    digest = _publication_digest(_receipt_to_json(provisional))
    receipt = PublicationReceipt(**{**provisional.__dict__, "publication_digest": digest})
    write_atomic_json(receipt_path, _receipt_to_json(receipt))
    return receipt
