"""Read-only API for validated canonical media frame timelines."""

from __future__ import annotations

from dataclasses import asdict

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .media_timeline_store import load_media_timeline
from .models import MediaAsset
from .storage import ObjectIntegrityError


@login_required
@require_GET
def media_timeline(request, media_id):
    membership = (
        request.user.wagvid_memberships.filter(active=True, organization__active=True)
        .select_related("organization")
        .first()
    )
    if not membership:
        return JsonResponse({"error": "no-active-organization"}, status=403)
    media = get_object_or_404(
        MediaAsset,
        pk=media_id,
        organization=membership.organization,
        state=MediaAsset.State.STORED,
    )
    try:
        timeline = load_media_timeline(media)
    except FileNotFoundError:
        return JsonResponse({"error": "canonical-timeline-not-ready"}, status=404)
    except (ObjectIntegrityError, ValueError) as error:
        return JsonResponse(
            {"error": "canonical-timeline-invalid", "detail": str(error)}, status=409
        )
    payload = {
        "schema": "ai.wagvid.canonical-timeline-api.v1",
        "source_sha256": timeline.source_sha256,
        "timeline_digest": timeline.digest,
        "stream_index": timeline.stream_index,
        "time_base": str(timeline.time_base),
        "diagnostics": asdict(timeline.diagnostics),
        "frames": [
            {
                "frame_index": frame.frame_index,
                "timestamp_s": timeline.timestamp_s(frame.frame_index),
                "pts": frame.pts,
                "dts": frame.dts,
                "key_frame": frame.key_frame,
            }
            for frame in timeline.frames
        ],
    }
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response
