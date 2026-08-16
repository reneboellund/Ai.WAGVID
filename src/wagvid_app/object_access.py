"""Short-lived object access grants portable across local and S3 backends."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode


class ObjectAccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class ObjectAccessGrant:
    organization_id: str
    object_key: str
    expires_at: int
    disposition: str
    content_sha256: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_object_access(
    grant: ObjectAccessGrant, *, secret: str, now: int | None = None,
    maximum_ttl_seconds: int = 3600,
) -> str:
    current = int(time.time()) if now is None else now
    if not secret or len(secret) < 32:
        raise ValueError("object access signing secret must be at least 32 characters")
    if grant.expires_at <= current or grant.expires_at - current > maximum_ttl_seconds:
        raise ValueError("object access expiry is outside the permitted window")
    if grant.disposition not in {"inline", "attachment"}:
        raise ValueError("invalid object disposition")
    if len(grant.content_sha256) != 64 or not grant.organization_id or not grant.object_key:
        raise ValueError("object access grant is incomplete")
    payload = json.dumps(grant.__dict__, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def verify_object_access(
    token: str, *, secret: str, organization_id: str,
    object_key: str, now: int | None = None,
) -> ObjectAccessGrant:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = _decode(encoded_payload)
        signature = _decode(encoded_signature)
        value = json.loads(payload)
        grant = ObjectAccessGrant(**value)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ObjectAccessDenied("malformed object access token") from error
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ObjectAccessDenied("invalid object access signature")
    current = int(time.time()) if now is None else now
    if grant.expires_at < current:
        raise ObjectAccessDenied("object access token has expired")
    if grant.organization_id != organization_id or grant.object_key != object_key:
        raise ObjectAccessDenied("object access scope mismatch")
    return grant


def signed_object_path(base_path: str, token: str) -> str:
    return f"{base_path}?{urlencode({'access': token})}"
