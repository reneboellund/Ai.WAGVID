"""Authenticated grant creation and signed immutable-media delivery."""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
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
    response = FileResponse(
        source, content_type=media.content_type or "application/octet-stream",
        as_attachment=grant.disposition == "attachment",
        filename=media.original_filename or f"{media.id}.bin",
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["ETag"] = f'"{media.sha256}"'
    return response
