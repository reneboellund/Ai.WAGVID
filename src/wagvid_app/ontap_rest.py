"""Dependency-light ONTAP REST transport primitives.

The client is intentionally small and injectable. Secrets exist only in process memory;
callers persist references through their configured secret store, not response payloads.
"""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


class OntapRestError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class OntapResponse:
    status: int
    payload: dict[str, Any]
    job_href: str | None = None


@dataclass(frozen=True)
class S3CredentialMaterial:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    key_expiry_time: str | None = None

    @property
    def fingerprint(self) -> str:
        return self.access_key[-4:].rjust(8, "*") if self.access_key else "missing"

    def redacted_summary(self) -> dict[str, str | None]:
        return {"access_key": self.fingerprint, "key_expiry_time": self.key_expiry_time}


Transport = Callable[[str, str, bytes | None, Mapping[str, str]], OntapResponse]


class OntapRestClient:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        ca_file: str | None = None,
        transport: Transport | None = None,
        timeout: float = 20.0,
    ):
        if not base_url.startswith("https://"):
            raise ValueError("ONTAP management API requires HTTPS")
        if not username or not password:
            raise ValueError("ONTAP management credentials are required")
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._ca_file = ca_file
        self._transport = transport
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        raw = f"{self._username}:{self._password}".encode()
        authorization = base64.b64encode(raw).decode("ascii")
        return {
            "Accept": "application/hal+json, application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {authorization}",
        }

    def _request(self, method: str, path: str, payload: dict | None = None) -> OntapResponse:
        if not path.startswith("/api/"):
            raise ValueError("ONTAP REST path must start with /api/")
        encoded = json.dumps(payload).encode() if payload is not None else None
        headers = self._headers()
        if self._transport:
            return self._transport(method, path, encoded, headers)

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            headers=headers,
            method=method,
        )
        context = ssl.create_default_context(cafile=self._ca_file)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=context) as response:
                body = response.read()
                value = json.loads(body.decode()) if body else {}
                job_href = None
                if isinstance(value, dict):
                    job_href = value.get("job", {}).get("_links", {}).get("self", {}).get("href")
                return OntapResponse(response.status, value, job_href)
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                value = json.loads(body.decode()) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                value = {}
            detail = value.get("error", {}) if isinstance(value, dict) else {}
            raise OntapRestError(
                detail.get("message") or f"ONTAP REST HTTP {error.code}",
                status=error.code,
                code=str(detail.get("code")) if detail.get("code") is not None else None,
            ) from error
        except urllib.error.URLError as error:
            raise OntapRestError(f"ONTAP REST connection failed: {error.reason}") from error

    def get(self, path: str) -> OntapResponse:
        return self._request("GET", path)

    def post(self, path: str, payload: dict) -> OntapResponse:
        return self._request("POST", path, payload)

    def patch(self, path: str, payload: dict) -> OntapResponse:
        return self._request("PATCH", path, payload)


def extract_s3_user_credentials(payload: Mapping[str, Any]) -> S3CredentialMaterial:
    """Extract a newly-created ONTAP S3 user's one-time key material."""
    source: Mapping[str, Any] = payload
    if isinstance(payload.get("records"), list) and payload["records"]:
        record = payload["records"][0]
        if isinstance(record, Mapping):
            source = record
    access_key = str(source.get("access_key") or "")
    secret_key = str(source.get("secret_key") or "")
    if not access_key or not secret_key:
        raise ValueError("ONTAP S3 user response did not contain access_key and secret_key")
    expiry = source.get("key_expiry_time")
    return S3CredentialMaterial(
        access_key=access_key,
        secret_key=secret_key,
        key_expiry_time=str(expiry) if expiry is not None else None,
    )
