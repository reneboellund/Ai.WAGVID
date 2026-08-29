"""Explicit opt-in contract validation for S3-compatible providers."""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

from .s3_storage import S3ObjectStore
from .storage_providers import CapabilityState, StorageCapability, evaluate_capabilities


@dataclass(frozen=True)
class StorageContractReport:
    provider_id: str
    bucket: str
    support_state: str
    verified: dict[str, str]
    checks: tuple[str, ...]
    issues: tuple[str, ...]


def run_storage_contract_probe(
    client,
    *,
    provider_id: str,
    governance_profile: str,
    bucket: str,
    test_prefix: str,
    allow_mutation: bool,
) -> StorageContractReport:
    """Validate safe object operations in a dedicated bucket/prefix.

    This function is never called by normal health checks or ordinary CI. The caller
    must explicitly allow temporary-object mutation.
    """

    if not allow_mutation:
        raise PermissionError("storage contract probe requires explicit mutation approval")
    prefix = test_prefix.strip("/")
    if not prefix or ".." in prefix.split("/"):
        raise ValueError("a safe dedicated test prefix is required")
    key = f"{prefix}/wagvid-contract-{uuid.uuid4().hex}.bin"
    multipart_key = f"{key}.multipart"
    payload = b"Ai.WAGVID storage contract probe"
    digest = hashlib.sha256(payload).hexdigest()
    store = S3ObjectStore(client, bucket=bucket)
    verified = {
        StorageCapability.SIGV4.value: CapabilityState.SUPPORTED.value,
    }
    checks = []
    issues = []
    version_id = ""
    try:
        stored = store.put_verified(
            key,
            io.BytesIO(payload),
            expected_size=len(payload),
            expected_sha256=digest,
            content_type="application/octet-stream",
        )
        version_id = stored.version_id
        checks.extend(("put", "head", "metadata-sha256"))
        if store.open_read(key, version_id=version_id).read() != payload:
            raise ValueError("full object read differs from probe payload")
        if store.open_range(key, start=3, end=11, version_id=version_id).read() != payload[3:12]:
            raise ValueError("range read differs from probe payload")
        verified[StorageCapability.RANGE_GET.value] = CapabilityState.SUPPORTED.value
        checks.extend(("get", "range-get"))
        try:
            store.presigned_download(key, version_id=version_id)
        except Exception as error:  # noqa: BLE001 - optional provider SDK errors
            verified[StorageCapability.PRESIGNED_GET.value] = CapabilityState.UNSUPPORTED.value
            issues.append(f"presigned-get unavailable: {type(error).__name__}")
        else:
            verified[StorageCapability.PRESIGNED_GET.value] = CapabilityState.SUPPORTED.value
            checks.append("presigned-get")

        session = store.start_multipart(multipart_key, sha256=digest)
        try:
            part = store.upload_part(session, number=1, payload=payload)
            listed = store.list_uploaded_parts(session)
            if not listed or listed[0]["PartNumber"] != 1:
                raise ValueError("uploaded multipart part was not discoverable")
            store.complete_multipart(session, parts=[part])
        except Exception:
            store.abort_multipart(session)
            raise
        verified[StorageCapability.MULTIPART.value] = CapabilityState.SUPPORTED.value
        checks.extend(("multipart-create", "multipart-list", "multipart-complete"))
    except Exception as error:  # noqa: BLE001 - contract records provider failure class
        issues.append(f"required contract operation failed: {type(error).__name__}")
    finally:
        for object_key, object_version in ((key, version_id), (multipart_key, "")):
            try:
                kwargs = {"Bucket": bucket, "Key": object_key}
                if object_version:
                    kwargs["VersionId"] = object_version
                client.delete_object(**kwargs)
            except Exception as error:  # noqa: BLE001 - immutable provider may reject cleanup
                issues.append(f"probe cleanup retained by provider: {type(error).__name__}")
            else:
                checks.append("delete-test-object")
    support_state, capability_issues = evaluate_capabilities(
        provider_id, governance_profile, verified
    )
    issues.extend(capability_issues)
    if any(item.startswith("required contract operation failed") for item in issues):
        support_state = "incompatible"
    return StorageContractReport(
        provider_id, bucket, support_state, verified, tuple(checks), tuple(sorted(set(issues)))
    )
