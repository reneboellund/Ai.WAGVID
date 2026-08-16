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
