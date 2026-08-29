"""Portable S3 provider certification records and safe opt-in contract probe.

Ordinary CI only exercises this module with fake clients. A real endpoint probe is an
explicit operator action against a dedicated bucket/prefix and never runs automatically.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from typing import Any

from .object_provider import StorageFeature


class ProviderSupportState(StrEnum):
    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    LIMITED = "limited"
    INCOMPATIBLE = "incompatible"


CORE_OPERATIONS = frozenset(
    {
        "head-bucket",
        "put-object",
        "head-object",
        "get-object",
        "range-get",
        "multipart-complete",
        "multipart-abort",
        "metadata-roundtrip",
    }
)


@dataclass(frozen=True)
class S3ContractValidation:
    provider_id: str
    bucket: str
    state: ProviderSupportState
    tested_at: datetime | None = None
    passed_operations: frozenset[str] = frozenset()
    failed_operations: tuple[tuple[str, str], ...] = ()
    verified_features: frozenset[StorageFeature] = frozenset()
    notes: tuple[str, ...] = ()

    @property
    def core_validated(self) -> bool:
        return CORE_OPERATIONS.issubset(self.passed_operations)

    def __post_init__(self) -> None:
        if not self.provider_id or not self.bucket:
            raise ValueError("provider_id and bucket are required")
        if self.tested_at is not None and (
            self.tested_at.tzinfo is None or self.tested_at.utcoffset() is None
        ):
            raise ValueError("tested_at must be timezone-aware")
        if self.state == ProviderSupportState.VALIDATED and not self.core_validated:
            raise ValueError("validated state requires all core S3 operations")


def support_state_for(
    passed: set[str], failed: list[tuple[str, str]]
) -> ProviderSupportState:
    if CORE_OPERATIONS.issubset(passed):
        return ProviderSupportState.VALIDATED if not failed else ProviderSupportState.LIMITED
    return ProviderSupportState.INCOMPATIBLE


def verified_features_for_operations(passed: set[str]) -> frozenset[StorageFeature]:
    features: set[StorageFeature] = set()
    if "range-get" in passed:
        features.add(StorageFeature.RANGE_GET)
    if {"multipart-complete", "multipart-abort"}.issubset(passed):
        features.add(StorageFeature.MULTIPART)
    if "presigned-get" in passed:
        features.add(StorageFeature.PRESIGNED_GET)
    if "presigned-put" in passed:
        features.add(StorageFeature.PRESIGNED_PUT)
    return frozenset(features)


def unvalidated(provider_id: str, bucket: str, *notes: str) -> S3ContractValidation:
    return S3ContractValidation(
        provider_id=provider_id,
        bucket=bucket,
        state=ProviderSupportState.UNVALIDATED,
        notes=tuple(notes),
    )


def run_safe_contract_probe(
    client: Any,
    *,
    provider_id: str,
    bucket: str,
    prefix: str = "ai-wagvid-capability-probe",
    allow_delete: bool = True,
    test_presign: bool = False,
    now: datetime | None = None,
) -> S3ContractValidation:
    """Run the explicit small-object/multipart contract probe required by conditional S3.

    This function is intentionally not wired to startup/health checks. The caller must
    opt in and choose a dedicated bucket/prefix. Cleanup is best-effort, and failures are
    recorded without converting provider exceptions into retry assumptions.
    """

    passed: set[str] = set()
    failed: list[tuple[str, str]] = []
    probe_id = uuid.uuid4().hex
    key = f"{prefix.strip('/')}/{probe_id}/small.bin"
    multipart_key = f"{prefix.strip('/')}/{probe_id}/multipart.bin"
    payload = b"Ai.WAGVID S3 capability probe v1\n"
    digest = hashlib.sha256(payload).hexdigest()

    def attempt(name: str, call):
        try:
            value = call()
            passed.add(name)
            return value
        except Exception as error:  # noqa: BLE001 - provider exceptions are recorded by type
            failed.append((name, type(error).__name__))
            return None

    attempt("head-bucket", lambda: client.head_bucket(Bucket=bucket))
    attempt(
        "put-object",
        lambda: client.put_object(
            Bucket=bucket,
            Key=key,
            Body=BytesIO(payload),
            Metadata={"sha256": digest},
        ),
    )
    head = attempt("head-object", lambda: client.head_object(Bucket=bucket, Key=key))
    if head is not None:
        metadata = {str(k).casefold(): str(v) for k, v in (head.get("Metadata") or {}).items()}
        if int(head.get("ContentLength", -1)) == len(payload) and metadata.get("sha256") == digest:
            passed.add("metadata-roundtrip")
        else:
            failed.append(("metadata-roundtrip", "mismatch"))

    response = attempt("get-object", lambda: client.get_object(Bucket=bucket, Key=key))
    if response is not None:
        body = response.get("Body")
        if body is None or body.read() != payload:
            passed.discard("get-object")
            failed.append(("get-object", "content-mismatch"))

    response = attempt(
        "range-get",
        lambda: client.get_object(Bucket=bucket, Key=key, Range="bytes=3-8"),
    )
    if response is not None:
        body = response.get("Body")
        if body is None or body.read() != payload[3:9]:
            passed.discard("range-get")
            failed.append(("range-get", "content-mismatch"))

    multipart = attempt(
        "multipart-create",
        lambda: client.create_multipart_upload(
            Bucket=bucket,
            Key=multipart_key,
            Metadata={"sha256": digest},
        ),
    )
    if multipart and multipart.get("UploadId"):
        upload_id = multipart["UploadId"]
        part = attempt(
            "multipart-upload",
            lambda: client.upload_part(
                Bucket=bucket,
                Key=multipart_key,
                UploadId=upload_id,
                PartNumber=1,
                Body=BytesIO(payload),
            ),
        )
        if part and part.get("ETag"):
            completed = attempt(
                "multipart-complete",
                lambda: client.complete_multipart_upload(
                    Bucket=bucket,
                    Key=multipart_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": part["ETag"]}]},
                ),
            )
            if completed is not None:
                completed_head = attempt(
                    "multipart-head",
                    lambda: client.head_object(Bucket=bucket, Key=multipart_key),
                )
                if completed_head is not None:
                    metadata = {
                        str(k).casefold(): str(v)
                        for k, v in (completed_head.get("Metadata") or {}).items()
                    }
                    if (
                        int(completed_head.get("ContentLength", -1)) != len(payload)
                        or metadata.get("sha256") != digest
                    ):
                        passed.discard("multipart-complete")
                        failed.append(("multipart-complete", "metadata-or-size-mismatch"))
                if allow_delete:
                    attempt(
                        "multipart-cleanup",
                        lambda: client.delete_object(Bucket=bucket, Key=multipart_key),
                    )
        else:
            attempt(
                "multipart-abort-after-upload-failure",
                lambda: client.abort_multipart_upload(
                    Bucket=bucket, Key=multipart_key, UploadId=upload_id
                ),
            )

    abort_key = f"{multipart_key}.abort"
    abort_probe = attempt(
        "multipart-abort-create",
        lambda: client.create_multipart_upload(Bucket=bucket, Key=abort_key),
    )
    if abort_probe and abort_probe.get("UploadId"):
        result = attempt(
            "multipart-abort",
            lambda: client.abort_multipart_upload(
                Bucket=bucket,
                Key=abort_key,
                UploadId=abort_probe["UploadId"],
            ),
        )
        if result is None:
            passed.discard("multipart-abort")

    if test_presign:
        generator = getattr(client, "generate_presigned_url", None)
        if generator is None:
            failed.append(("presigned-get", "unsupported"))
        else:
            attempt(
                "presigned-get",
                lambda: generator(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=60,
                ),
            )

    if allow_delete:
        attempt("delete-object", lambda: client.delete_object(Bucket=bucket, Key=key))

    state = support_state_for(passed, failed)
    return S3ContractValidation(
        provider_id=provider_id,
        bucket=bucket,
        state=state,
        tested_at=now or datetime.now(UTC),
        passed_operations=frozenset(passed),
        failed_operations=tuple(failed),
        verified_features=verified_features_for_operations(passed),
    )
