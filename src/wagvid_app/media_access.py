"""Authenticated grant creation and signed immutable-media delivery."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import BinaryIO

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import (
    FileResponse,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_POST

from .models import MediaAsset
from .object_access import (
    ObjectAccessDenied,
    ObjectAccessGrant,
    sign_object_access,
    verify_object_access,
)
from .storage import LocalObjectStore, ObjectIntegrityError
from .views import active_organization


@login_required
@require_POST
def create_media_grant(request, media_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    media = get_object_or_404(
        MediaAsset, pk=media_id, organization=organization, state=MediaAsset.State.STORED
    )
    if not media.object_key or len(media.sha256) != 64:
        return JsonResponse({"error": "media-integrity-incomplete"}, status=409)
    now = int(time.time())
    ttl = settings.WAGVID_OBJECT_GRANT_TTL_SECONDS
    grant = ObjectAccessGrant(
        str(organization.id), media.object_key, now + ttl,
        request.POST.get("disposition", "inline"), media.sha256,
    )
    try:
        token = sign_object_access(
            grant, secret=settings.WAGVID_OBJECT_SIGNING_SECRET,
            now=now, maximum_ttl_seconds=ttl,
        )
    except ValueError as error:
        return JsonResponse({"error": "invalid-access-request", "detail": str(error)}, status=400)
    path = reverse("media-object-download", args=[media.id])
    organization.audit_events.create(
        actor=request.user, action="media.access-granted", object_type="media-asset",
        object_id=str(media.id), metadata={"expires_at": grant.expires_at},
    )
    return JsonResponse({"url": f"{path}?access={token}", "expires_at": grant.expires_at})


def _parse_single_range(value: str, *, size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range; multi-range requests are intentionally unsupported."""

    if size <= 0:
        raise ValueError("range unavailable for empty object")
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        raise ValueError("invalid or multiple byte range")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise ValueError("empty byte range")
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        length = min(suffix, size)
        return size - length, size - 1
    start = int(start_text)
    if start >= size:
        raise ValueError("range starts beyond object")
    end = int(end_text) if end_text else size - 1
    if end < start:
        raise ValueError("range end precedes start")
    return start, min(end, size - 1)


def _stream_range(source: BinaryIO, *, start: int, length: int) -> Iterator[bytes]:
    source.seek(start)
    remaining = length
    try:
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        source.close()


def _security_headers(response, *, sha256: str) -> None:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Accept-Ranges"] = "bytes"
    response["ETag"] = f'"{sha256}"'


@require_GET
def download_media_object(request, media_id):
    media = get_object_or_404(MediaAsset.objects.select_related("organization"), pk=media_id)
    token = request.GET.get("access", "")
    try:
        grant = verify_object_access(
            token, secret=settings.WAGVID_OBJECT_SIGNING_SECRET,
            organization_id=str(media.organization_id), object_key=media.object_key,
        )
        if grant.content_sha256 != media.sha256:
            raise ObjectAccessDenied("object checksum scope mismatch")
        store = LocalObjectStore()
        stored = store.inspect(media.object_key)
        if stored.sha256 != media.sha256:
            raise ObjectIntegrityError("stored object checksum differs from media record")
        source = store.open_read(media.object_key)
    except (ObjectAccessDenied, ObjectIntegrityError, FileNotFoundError, ValueError):
        return JsonResponse({"error": "object-access-denied"}, status=403)

    range_header = request.headers.get("Range")
    if range_header:
        try:
            start, end = _parse_single_range(range_header, size=stored.size)
        except ValueError:
            source.close()
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{stored.size}"
            _security_headers(response, sha256=media.sha256)
            return response
        length = end - start + 1
        response = StreamingHttpResponse(
            _stream_range(source, start=start, length=length),
            status=206,
            content_type=media.content_type or "application/octet-stream",
        )
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{stored.size}"
        response["Content-Disposition"] = content_disposition_header(
            grant.disposition == "attachment",
            media.original_filename or f"{media.id}.bin",
        )
        _security_headers(response, sha256=media.sha256)
        return response

    response = FileResponse(
        source, content_type=media.content_type or "application/octet-stream",
        as_attachment=grant.disposition == "attachment",
        filename=media.original_filename or f"{media.id}.bin",
    )
    _security_headers(response, sha256=media.sha256)
    return response
