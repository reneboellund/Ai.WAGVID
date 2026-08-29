"""Integrity-first S3/Wasabi data-plane adapter.

The adapter is deliberately independent from Django models. Lifecycle authorization,
bucket routing and database registration remain control-plane responsibilities.
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Protocol

from .storage import ObjectIntegrityError, StoredObject

MIB = 1024 * 1024


class S3DataClient(Protocol):
    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def create_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...
    def upload_part(self, **kwargs: Any) -> dict[str, Any]: ...
    def complete_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...
    def abort_multipart_upload(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_parts(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...
    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...


def _not_found(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def _validate_key(key: str) -> None:
    path = PurePosixPath(key)
    if (
        not key
        or path.is_absolute()
        or ".." in path.parts
        or len(key.encode("utf-8")) > 1024
        or any(ord(character) < 32 for character in key)
    ):
        raise ValueError("unsafe S3 object key")


@dataclass(frozen=True)
class S3StoredObject(StoredObject):
    bucket: str
    version_id: str = ""
    etag: str = ""


@dataclass(frozen=True)
class MultipartSession:
    bucket: str
    key: str
    upload_id: str
    sha256: str


class S3ObjectStore:
    """Immutable verified writes with automatic multipart upload for large objects."""

    def __init__(
        self,
        client: S3DataClient,
        *,
        bucket: str,
        multipart_threshold: int = 100 * MIB,
        part_size: int = 16 * MIB,
    ):
        if not bucket or multipart_threshold < 5 * MIB or part_size < 5 * MIB:
            raise ValueError("bucket and S3-compatible upload sizes are required")
        self.client = client
        self.bucket = bucket
        self.multipart_threshold = multipart_threshold
        self.part_size = part_size

    def _head(self, key: str) -> dict[str, Any] | None:
        _validate_key(key)
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if _not_found(error):
                return None
            raise

    def inspect(self, key: str) -> S3StoredObject:
        head = self._head(key)
        if head is None:
            raise FileNotFoundError(key)
        metadata = {str(k).lower(): str(v) for k, v in head.get("Metadata", {}).items()}
        sha256 = metadata.get("sha256", "")
        if len(sha256) != 64:
            raise ObjectIntegrityError("S3 object lacks immutable SHA-256 metadata")
        return S3StoredObject(
            key=key,
            size=int(head["ContentLength"]),
            sha256=sha256,
            bucket=self.bucket,
            version_id=str(head.get("VersionId", "")),
            etag=str(head.get("ETag", "")).strip('"'),
        )

    def put_verified(
        self,
        key: str,
        source: BinaryIO,
        *,
        expected_size: int,
        expected_sha256: str,
        content_type: str = "application/octet-stream",
    ) -> S3StoredObject:
        if expected_size < 0 or len(expected_sha256) != 64:
            raise ValueError("valid expected size and SHA-256 are required")
        existing = self._head(key)
        if existing is not None:
            stored = self.inspect(key)
            if stored.size == expected_size and stored.sha256 == expected_sha256.lower():
                return stored
            raise ObjectIntegrityError("Immutable object key already contains different content")

        with tempfile.SpooledTemporaryFile(max_size=32 * MIB) as staged:
            digest = hashlib.sha256()
            size = 0
            while chunk := source.read(MIB):
                digest.update(chunk)
                size += len(chunk)
                staged.write(chunk)
            actual = digest.hexdigest()
            if size != expected_size or actual != expected_sha256.lower():
                raise ObjectIntegrityError("Uploaded object does not match size/checksum")
            staged.seek(0)
            if size >= self.multipart_threshold:
                response = self._multipart_put(key, staged, actual, content_type)
            else:
                response = self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=staged,
                    ContentLength=size,
                    ContentType=content_type,
                    Metadata={"sha256": actual},
                    ServerSideEncryption="AES256",
                    ChecksumSHA256=base64.b64encode(bytes.fromhex(actual)).decode("ascii"),
                )
        return S3StoredObject(
            key, size, actual, self.bucket,
            str(response.get("VersionId", "")), str(response.get("ETag", "")).strip('"'),
        )

    def _multipart_put(
        self, key: str, staged: BinaryIO, sha256: str, content_type: str
    ) -> dict[str, Any]:
        session = self.start_multipart(key, sha256=sha256, content_type=content_type)
        parts = []
        try:
            number = 1
            while chunk := staged.read(self.part_size):
                parts.append(self.upload_part(session, number=number, payload=chunk))
                number += 1
            return self.complete_multipart(session, parts=parts)
        except Exception:
            self.abort_multipart(session)
            raise

    def start_multipart(
        self, key: str, *, sha256: str, content_type: str = "application/octet-stream"
    ) -> MultipartSession:
        _validate_key(key)
        if len(sha256) != 64:
            raise ValueError("valid object SHA-256 is required")
        started = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type,
            Metadata={"sha256": sha256.lower()},
            ServerSideEncryption="AES256",
            ChecksumAlgorithm="SHA256",
        )
        return MultipartSession(self.bucket, key, started["UploadId"], sha256.lower())

    def upload_part(
        self, session: MultipartSession, *, number: int, payload: bytes
    ) -> dict[str, Any]:
        self._validate_session(session)
        if number < 1 or number > 10_000 or not payload:
            raise ValueError("multipart part number and payload are invalid")
        checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
        result = self.client.upload_part(
            Bucket=self.bucket,
            Key=session.key,
            UploadId=session.upload_id,
            PartNumber=number,
            Body=payload,
            ContentLength=len(payload),
            ChecksumSHA256=checksum,
        )
        part = {"PartNumber": number, "ETag": result["ETag"]}
        if result.get("ChecksumSHA256"):
            part["ChecksumSHA256"] = result["ChecksumSHA256"]
        return part

    def list_uploaded_parts(self, session: MultipartSession) -> tuple[dict[str, Any], ...]:
        self._validate_session(session)
        result = self.client.list_parts(
            Bucket=self.bucket, Key=session.key, UploadId=session.upload_id
        )
        return tuple(
            {
                "PartNumber": int(part["PartNumber"]),
                "ETag": part["ETag"],
                **({"ChecksumSHA256": part["ChecksumSHA256"]} if part.get("ChecksumSHA256") else {}),
            }
            for part in result.get("Parts", [])
        )

    def complete_multipart(
        self, session: MultipartSession, *, parts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self._validate_session(session)
        if not parts:
            raise ValueError("multipart completion requires uploaded parts")
        return self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=session.key,
            UploadId=session.upload_id,
            MultipartUpload={"Parts": parts},
        )

    def abort_multipart(self, session: MultipartSession) -> None:
        self._validate_session(session)
        self.client.abort_multipart_upload(
            Bucket=self.bucket, Key=session.key, UploadId=session.upload_id
        )

    def _validate_session(self, session: MultipartSession) -> None:
        if session.bucket != self.bucket or not session.upload_id:
            raise ValueError("multipart session belongs to another storage target")
        _validate_key(session.key)

    def open_read(self, key: str, *, version_id: str = "") -> BinaryIO:
        _validate_key(key)
        kwargs = {"Bucket": self.bucket, "Key": key}
        if version_id:
            kwargs["VersionId"] = version_id
        response = self.client.get_object(**kwargs)
        return response["Body"]

    def open_range(
        self, key: str, *, start: int, end: int | None = None, version_id: str = ""
    ) -> BinaryIO:
        _validate_key(key)
        if start < 0 or (end is not None and end < start):
            raise ValueError("invalid object byte range")
        kwargs = {
            "Bucket": self.bucket,
            "Key": key,
            "Range": f"bytes={start}-{'' if end is None else end}",
        }
        if version_id:
            kwargs["VersionId"] = version_id
        return self.client.get_object(**kwargs)["Body"]

    def presigned_download(
        self, key: str, *, expires_seconds: int = 300, version_id: str = ""
    ) -> str:
        _validate_key(key)
        if not 1 <= expires_seconds <= 3600:
            raise ValueError("download expiry must be between 1 and 3600 seconds")
        params = {"Bucket": self.bucket, "Key": key}
        if version_id:
            params["VersionId"] = version_id
        return self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_seconds
        )

    def delete_version(self, key: str, *, version_id: str) -> None:
        """Delete only an explicitly registered version; lifecycle policy is external."""

        _validate_key(key)
        if not version_id:
            raise ValueError("an explicit object version is required for physical deletion")
        self.client.delete_object(Bucket=self.bucket, Key=key, VersionId=version_id)
