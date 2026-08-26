"""Small provider-neutral object-storage value types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


class BucketRole(StrEnum):
    ORIGINALS = "originals"
    DERIVATIVES = "derivatives"
    METADATA = "metadata"
    RESULTS = "results"
    AUDIT = "audit"


@dataclass(frozen=True)
class DesiredBucket:
    name: str
    role: BucketRole
    shard: int
    region: str
    private: bool
    versioning: bool
    object_lock: bool


def route_object(
    *, role: BucketRole, routing_key: str, buckets: tuple[DesiredBucket, ...]
) -> DesiredBucket:
    candidates = [bucket for bucket in buckets if bucket.role is role]
    if not candidates or not routing_key:
        raise ValueError("routing requires a key and at least one bucket for the role")
    return max(
        candidates,
        key=lambda bucket: hashlib.sha256(f"{routing_key}|{bucket.name}".encode()).digest(),
    )
