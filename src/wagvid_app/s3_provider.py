"""Generic capability-driven S3 data-plane and preflight helpers.

No provider is treated as fully AWS-compatible merely because it speaks S3. Endpoint
capabilities are conservative and provider adapters may add only features that have
been validated for that provider/profile.
"""

from __future__ import annotations

import hashlib
import importlib
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

from .object_provider import (
    ObjectLocation,
    ProviderType,
    StorageCapabilities,
    StorageConnectionProfile,
    StorageFeature,
    StoragePreflight,
)
from .storage import ObjectIntegrityError, StoredObject


class S3ProviderError(RuntimeError):
    pass


class S3InspectionClient(Protocol):
    def head_bucket(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_object_lock_configuration(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_lifecycle_configuration(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_policy(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_public_access_block(self, *, Bucket: str) -> dict[str, Any]: ...


class S3DataClient(S3InspectionClient, Protocol):
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...
    def upload_part(self, **kwargs: Any) -> dict[str, Any]: ...
    def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...
    def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class BucketProbe:
    bucket: str
    reachable: bool
    features: frozenset[StorageFeature]
    versioning_state: str | None = None
    object_lock_enabled: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultipartHandle:
    location: ObjectLocation
    upload_id: str
    expected_sha256: str


@dataclass(frozen=True)
class MultipartUploadInfo:
    bucket: str
    key: str
    upload_id: str
    initiated: str | None = None


@dataclass(frozen=True)
class MultipartDiagnostics:
    uploads: tuple[MultipartUploadInfo, ...]
    truncated: bool = False


@dataclass(frozen=True)
class PresignedRequest:
    url: str
    headers: dict[str, str]
    expires_seconds: int


@dataclass(frozen=True)
class S3TransferTuning:
    multipart_threshold_bytes: int = 64 * 1024 * 1024
    part_size_bytes: int = 16 * 1024 * 1024
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        if self.multipart_threshold_bytes < 1:
            raise ValueError("multipart_threshold_bytes must be positive")
        if self.part_size_bytes < 5 * 1024 * 1024:
            raise ValueError("part_size_bytes must be at least 5 MiB")
        if not 1 <= self.max_concurrency <= 64:
            raise ValueError("max_concurrency must be between 1 and 64")


def _attempt(call, *args, **kwargs):
    try:
        return True, call(*args, **kwargs), None
    except Exception as error:  # noqa: BLE001 - provider SDK exceptions are optional
        return False, None, type(error).__name__


def _attempt_named(client: Any, name: str, **kwargs):
    call = getattr(client, name, None)
    if call is None:
        return False, None, "unsupported"
    return _attempt(call, **kwargs)


def inspect_bucket(client: S3InspectionClient, bucket: str) -> BucketProbe:
    reachable, _, head_error = _attempt(client.head_bucket, Bucket=bucket)
    if not reachable:
        return BucketProbe(
            bucket=bucket,
            reachable=False,
            features=frozenset(),
            warnings=(f"head-bucket:{head_error}",),
        )

    features: set[StorageFeature] = set()
    warnings: list[str] = []
    versioning_state = None
    object_lock_enabled = None

    ok, value, error = _attempt(client.get_bucket_versioning, Bucket=bucket)
    if ok:
        versioning_state = str((value or {}).get("Status") or "Disabled")
        if versioning_state == "Enabled":
            features.add(StorageFeature.VERSIONING)
        else:
            warnings.append(f"versioning-not-enabled:{versioning_state}")
    else:
        warnings.append(f"versioning-unverified:{error}")

    ok, value, error = _attempt(client.get_object_lock_configuration, Bucket=bucket)
    if ok:
        configuration = (value or {}).get("ObjectLockConfiguration", {})
        object_lock_enabled = configuration.get("ObjectLockEnabled") == "Enabled"
        if object_lock_enabled:
            features.add(StorageFeature.OBJECT_LOCK)
        else:
            warnings.append("object-lock-not-enabled")
        # Legal hold is deliberately not inferred from Object Lock support.
    else:
        warnings.append(f"object-lock-unverified:{error}")

    ok, value, error = _attempt(client.get_bucket_lifecycle_configuration, Bucket=bucket)
    if ok and (value or {}).get("Rules") is not None:
        features.add(StorageFeature.LIFECYCLE)
    else:
        warnings.append(f"lifecycle-unverified:{error or 'no-rules'}")

    ok, _, error = _attempt(client.get_bucket_policy, Bucket=bucket)
    if ok:
        features.add(StorageFeature.BUCKET_POLICY)
    else:
        warnings.append(f"bucket-policy-unverified:{error}")

    ok, value, error = _attempt(client.get_public_access_block, Bucket=bucket)
    if ok:
        block = (value or {}).get("PublicAccessBlockConfiguration", {})
        required = (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
        if all(block.get(key) is True for key in required):
            features.add(StorageFeature.PUBLIC_ACCESS_BLOCK)
        else:
            warnings.append("public-access-block-not-fully-enabled")
    else:
        warnings.append(f"public-access-block-unverified:{error}")

    ok, value, error = _attempt_named(client, "get_bucket_encryption", Bucket=bucket)
    if ok and (value or {}).get("ServerSideEncryptionConfiguration", {}).get("Rules"):
        features.add(StorageFeature.SERVER_SIDE_ENCRYPTION)
    elif error != "unsupported":
        warnings.append(f"server-side-encryption-unverified:{error or 'not-configured'}")

    return BucketProbe(
        bucket=bucket,
        reachable=True,
        features=frozenset(features),
        versioning_state=versioning_state,
        object_lock_enabled=object_lock_enabled,
        warnings=tuple(warnings),
    )


def preflight_existing_buckets(
    profile: StorageConnectionProfile,
    client: S3InspectionClient,
    *,
    buckets: list[str],
    extra_verified_features: frozenset[StorageFeature] = frozenset(),
) -> tuple[StoragePreflight, tuple[BucketProbe, ...]]:
    probes = tuple(inspect_bucket(client, bucket) for bucket in sorted(set(buckets)))
    reachable = [probe for probe in probes if probe.reachable]
    blockers = tuple(
        f"bucket-unreachable:{probe.bucket}" for probe in probes if not probe.reachable
    )
    common_features: set[StorageFeature] = set(extra_verified_features)
    if reachable:
        endpoint_features = set(reachable[0].features)
        for probe in reachable[1:]:
            endpoint_features.intersection_update(probe.features)
        common_features.update(endpoint_features)
    warnings = tuple(
        f"{probe.bucket}:{warning}" for probe in probes for warning in probe.warnings
    )
    return (
        StoragePreflight(
            connected=bool(probes) and not blockers,
            capabilities=StorageCapabilities(features=frozenset(common_features)),
            identity_summary=f"{profile.provider_type.value}:{profile.provider_id}",
            warnings=warnings,
            blockers=blockers,
        ),
        probes,
    )


def _read_all_verified(
    source: BinaryIO, *, expected_size: int, expected_sha256: str
) -> BinaryIO:
    expected = expected_sha256.casefold()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected_sha256 must be a lowercase-compatible SHA-256 hex digest")
    digest = hashlib.sha256()
    size = 0
    # Ownership is transferred to the caller on success, so a context manager cannot close it here.
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115
    try:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            spool.write(chunk)
        if size != expected_size or digest.hexdigest() != expected:
            raise ObjectIntegrityError("Source object does not match expected size/checksum")
        spool.seek(0)
        return spool
    except Exception:
        spool.close()
        raise


class S3ObjectStorageProvider:
    """Provider-neutral S3 data plane with immutable identity/checksum semantics."""

    def __init__(
        self,
        profile: StorageConnectionProfile,
        client: S3DataClient,
        *,
        buckets: Iterable[str],
        verified_features: frozenset[StorageFeature] = frozenset(),
        transfer_tuning: S3TransferTuning | None = None,
    ) -> None:
        self.profile = profile
        self.client = client
        self.provider_id = profile.provider_id
        self.buckets = tuple(sorted(set(buckets)))
        self.verified_features = verified_features
        self.transfer_tuning = transfer_tuning or S3TransferTuning()
        if not self.buckets:
            raise ValueError("At least one configured bucket is required")

    def replace_client(self, client: S3DataClient) -> None:
        """Rotate resolved credentials/client without changing provider/object identity."""
        self.client = client

    def _location_kwargs(self, location: ObjectLocation) -> dict[str, Any]:
        if location.provider_id != self.provider_id:
            raise ValueError("Object location belongs to another storage provider")
        if location.bucket not in self.buckets:
            raise ValueError("Object location bucket is not mapped to this provider")
        kwargs: dict[str, Any] = {"Bucket": location.bucket, "Key": location.key}
        if location.version_id:
            kwargs["VersionId"] = location.version_id
        return kwargs

    def preflight(self) -> StoragePreflight:
        preflight, _ = preflight_existing_buckets(
            self.profile,
            self.client,
            buckets=list(self.buckets),
            extra_verified_features=self.verified_features,
        )
        return preflight

    def put_verified(
        self,
        location: ObjectLocation,
        source: BinaryIO,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredObject:
        if location.version_id:
            raise ValueError("A write cannot target an existing object version")
        kwargs = self._location_kwargs(location)
        verified = _read_all_verified(
            source, expected_size=expected_size, expected_sha256=expected_sha256
        )
        try:
            self.client.put_object(
                **kwargs,
                Body=verified,
                Metadata={"sha256": expected_sha256.casefold()},
            )
        finally:
            verified.close()
        stored = self.inspect(location)
        if stored.size != expected_size or stored.sha256 != expected_sha256.casefold():
            raise ObjectIntegrityError("Stored object does not match expected size/checksum")
        return stored

    def inspect(self, location: ObjectLocation) -> StoredObject:
        response = self.client.head_object(**self._location_kwargs(location))
        metadata = {str(k).casefold(): str(v) for k, v in (response.get("Metadata") or {}).items()}
        sha256 = metadata.get("sha256", "").casefold()
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise ObjectIntegrityError(
                "Stored object has no valid canonical sha256 metadata; verify/import it before use"
            )
        return StoredObject(
            key=location.key,
            size=int(response["ContentLength"]),
            sha256=sha256,
        )

    def open_read(self, location: ObjectLocation) -> BinaryIO:
        response = self.client.get_object(**self._location_kwargs(location))
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise S3ProviderError("S3 get_object returned no readable body")
        return body

    def open_range(self, location: ObjectLocation, *, start: int, end: int | None = None) -> BinaryIO:
        if start < 0 or (end is not None and end < start):
            raise ValueError("Invalid byte range")
        kwargs = self._location_kwargs(location)
        kwargs["Range"] = f"bytes={start}-{'' if end is None else end}"
        response = self.client.get_object(**kwargs)
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise S3ProviderError("S3 Range GET returned no readable body")
        return body

    def delete(self, location: ObjectLocation) -> None:
        self.client.delete_object(**self._location_kwargs(location))

    def create_multipart(
        self, location: ObjectLocation, *, expected_sha256: str
    ) -> MultipartHandle:
        if location.version_id:
            raise ValueError("A multipart write cannot target an existing object version")
        expected = expected_sha256.casefold()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        response = self.client.create_multipart_upload(
            **self._location_kwargs(location), Metadata={"sha256": expected}
        )
        upload_id = str(response.get("UploadId") or "")
        if not upload_id:
            raise S3ProviderError("S3 create_multipart_upload returned no UploadId")
        return MultipartHandle(location, upload_id, expected)

    def upload_part(
        self, handle: MultipartHandle, *, part_number: int, body: BinaryIO
    ) -> str:
        if part_number < 1 or part_number > 10_000:
            raise ValueError("S3 multipart part number must be between 1 and 10000")
        response = self.client.upload_part(
            **self._location_kwargs(handle.location),
            UploadId=handle.upload_id,
            PartNumber=part_number,
            Body=body,
        )
        etag = str(response.get("ETag") or "")
        if not etag:
            raise S3ProviderError("S3 upload_part returned no ETag")
        return etag

    def complete_multipart(
        self,
        handle: MultipartHandle,
        *,
        parts: Iterable[tuple[int, str]],
        expected_size: int,
    ) -> StoredObject:
        normalized = [
            {"PartNumber": number, "ETag": etag}
            for number, etag in sorted(parts, key=lambda item: item[0])
        ]
        if not normalized:
            raise ValueError("At least one multipart part is required")
        self.client.complete_multipart_upload(
            **self._location_kwargs(handle.location),
            UploadId=handle.upload_id,
            MultipartUpload={"Parts": normalized},
        )
        stored = self.inspect(handle.location)
        if stored.size != expected_size or stored.sha256 != handle.expected_sha256:
            raise ObjectIntegrityError("Completed multipart object failed size/checksum metadata validation")
        return stored

    def abort_multipart(self, handle: MultipartHandle) -> None:
        self.client.abort_multipart_upload(
            **self._location_kwargs(handle.location), UploadId=handle.upload_id
        )

    def multipart_diagnostics(self, *, bucket: str, prefix: str = "") -> MultipartDiagnostics:
        if StorageFeature.MULTIPART not in self.verified_features:
            raise S3ProviderError("Multipart diagnostics are not validated for this provider")
        if bucket not in self.buckets:
            raise ValueError("Bucket is not mapped to this provider")
        call = getattr(self.client, "list_multipart_uploads", None)
        if call is None:
            raise S3ProviderError("Provider client does not expose multipart diagnostics")
        response = call(Bucket=bucket, Prefix=prefix)
        uploads = tuple(
            MultipartUploadInfo(
                bucket=bucket,
                key=str(item.get("Key") or ""),
                upload_id=str(item.get("UploadId") or ""),
                initiated=str(item.get("Initiated")) if item.get("Initiated") is not None else None,
            )
            for item in response.get("Uploads", [])
            if item.get("Key") and item.get("UploadId")
        )
        return MultipartDiagnostics(uploads=uploads, truncated=bool(response.get("IsTruncated")))

    def presign_get(self, location: ObjectLocation, *, expires_seconds: int = 300) -> PresignedRequest:
        if StorageFeature.PRESIGNED_GET not in self.verified_features:
            raise S3ProviderError("Presigned GET is not validated for this provider")
        if not 1 <= expires_seconds <= 3600:
            raise ValueError("expires_seconds must be between 1 and 3600")
        generator = getattr(self.client, "generate_presigned_url", None)
        if generator is None:
            raise S3ProviderError("Provider client cannot generate presigned URLs")
        url = generator(
            "get_object",
            Params=self._location_kwargs(location),
            ExpiresIn=expires_seconds,
        )
        return PresignedRequest(str(url), {}, expires_seconds)

    def presign_put(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str,
        expires_seconds: int = 300,
    ) -> PresignedRequest:
        if StorageFeature.PRESIGNED_PUT not in self.verified_features:
            raise S3ProviderError("Presigned PUT is not validated for this provider")
        if location.version_id:
            raise ValueError("A presigned PUT cannot target an existing object version")
        if not 1 <= expires_seconds <= 3600:
            raise ValueError("expires_seconds must be between 1 and 3600")
        expected = expected_sha256.casefold()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        generator = getattr(self.client, "generate_presigned_url", None)
        if generator is None:
            raise S3ProviderError("Provider client cannot generate presigned URLs")
        params = self._location_kwargs(location)
        params["Metadata"] = {"sha256": expected}
        url = generator("put_object", Params=params, ExpiresIn=expires_seconds)
        return PresignedRequest(
            str(url),
            {"x-amz-meta-sha256": expected},
            expires_seconds,
        )


def create_boto3_s3_client(
    profile: StorageConnectionProfile,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    session_token: str | None = None,
    ca_bundle_path: str | None = None,
):
    """Lazy boto3 factory supporting AWS credential chain or resolved S3 credentials."""
    try:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
    except ImportError as error:
        raise S3ProviderError("Install the optional S3 provider dependencies") from error

    style = None if profile.addressing_style == "auto" else profile.addressing_style
    config_kwargs: dict[str, Any] = {}
    if style:
        config_kwargs["s3"] = {"addressing_style": style}
    config = botocore_config.Config(**config_kwargs)
    kwargs: dict[str, Any] = {"config": config}
    if profile.endpoint:
        kwargs["endpoint_url"] = profile.endpoint
    if profile.region:
        kwargs["region_name"] = profile.region
    if profile.ca_bundle_ref and not ca_bundle_path:
        raise S3ProviderError("Resolve ca_bundle_ref to a verified local CA path before client creation")
    if ca_bundle_path:
        kwargs["verify"] = ca_bundle_path
    if access_key_id is not None:
        kwargs["aws_access_key_id"] = access_key_id
    if secret_access_key is not None:
        kwargs["aws_secret_access_key"] = secret_access_key
    if session_token is not None:
        kwargs["aws_session_token"] = session_token
    return boto3.client("s3", **kwargs)


def default_provider_features(provider_type: ProviderType) -> frozenset[StorageFeature]:
    """Return only features safe to assume before endpoint/profile certification."""
    if provider_type == ProviderType.LOCAL:
        return frozenset({StorageFeature.RANGE_GET})
    return frozenset()
