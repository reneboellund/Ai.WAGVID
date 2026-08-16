import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from django.conf import settings


class ObjectIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class LocalObjectStore:
    """Development object store with production-compatible integrity semantics."""

    def __init__(self, root: Path | None = None):
        self.root = (root or settings.WAGVID_OBJECT_ROOT).resolve()

    def _path(self, key: str) -> Path:
        normalized = PurePosixPath(key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("Unsafe object key")
        path = (self.root / Path(*normalized.parts)).resolve()
        if self.root not in path.parents:
            raise ValueError("Object key escapes storage root")
        return path

    def put_verified(
        self, key: str, source: BinaryIO, *, expected_size: int, expected_sha256: str
    ) -> StoredObject:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = self.inspect(key)
            if existing.size == expected_size and existing.sha256 == expected_sha256:
                return existing
            raise ObjectIntegrityError("Immutable object key already contains different content")
        temporary = destination.with_suffix(destination.suffix + ".partial")
        digest = hashlib.sha256()
        size = 0
        with temporary.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
        actual_sha256 = digest.hexdigest()
        if size != expected_size or actual_sha256 != expected_sha256:
            temporary.unlink(missing_ok=True)
            raise ObjectIntegrityError("Uploaded object does not match size/checksum")
        os.replace(temporary, destination)
        return StoredObject(key=key, size=size, sha256=actual_sha256)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def inspect(self, key: str) -> StoredObject:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return StoredObject(key, size, digest.hexdigest())

    def open_read(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.open("rb")

    def append_chunk(self, key: str, source: BinaryIO, *, offset: int, max_bytes: int) -> int:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        current_size = destination.stat().st_size if destination.exists() else 0
        if offset != current_size:
            raise ValueError(f"Expected offset {current_size}, received {offset}")
        written = 0
        with destination.open("ab") as target:
            while chunk := source.read(min(1024 * 1024, max_bytes - written + 1)):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Chunk exceeds configured maximum")
                target.write(chunk)
        return current_size + written

    def finalize_partial(
        self,
        partial_key: str,
        final_key: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredObject:
        partial = self._path(partial_key)
        if not partial.is_file():
            raise FileNotFoundError(partial_key)
        digest = hashlib.sha256()
        size = 0
        with partial.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        if size != expected_size or actual_sha256 != expected_sha256:
            raise ObjectIntegrityError("Partial upload does not match size/checksum")
        final = self._path(final_key)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            existing = self.inspect(final_key)
            if existing.size != expected_size or existing.sha256 != expected_sha256:
                raise ObjectIntegrityError("Immutable object key already contains different content")
            partial.unlink(missing_ok=True)
            return existing
        os.replace(partial, final)
        return StoredObject(final_key, size, actual_sha256)
