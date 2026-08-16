import io
import json
import re
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import Device, Gymnast, MediaAsset, UploadSession
from .operations import UploadRequest, checkpoint_upload, open_upload
from .storage import LocalObjectStore, ObjectIntegrityError


def authenticate_device(request: HttpRequest) -> Device | None:
    device_key = request.headers.get("X-WAGVID-Device")
    authorization = request.headers.get("Authorization", "")
    if not device_key or not authorization.startswith("Bearer "):
        return None
    device = Device.objects.filter(device_key=device_key).first()
    token = authorization.removeprefix("Bearer ")
    return device if device and device.check_api_token(token) else None


def unauthorized() -> JsonResponse:
    return JsonResponse({"error": "device-authentication-required"}, status=401)


@csrf_exempt
@require_POST
def upload_open(request: HttpRequest) -> JsonResponse:
    device = authenticate_device(request)
    if not device:
        return unauthorized()
    try:
        payload = json.loads(request.body)
        gymnast = Gymnast.objects.get(
            pk=UUID(payload["gymnast_id"]),
            organization=device.organization,
            archived_at__isnull=True,
        )
        expected_bytes = int(payload["expected_bytes"])
        if not 0 < expected_bytes <= settings.WAGVID_MAX_UPLOAD_BYTES:
            raise ValueError("invalid expected size")
        filename = PurePosixPath(str(payload["local_filename"]).replace("\\", "/")).name
        recorded_at = datetime.fromisoformat(payload["recorded_at"])
        if timezone.is_naive(recorded_at):
            raise ValueError("recorded_at must include a timezone")
        upload_request = UploadRequest(
            capture_id=UUID(payload["capture_id"]),
            idempotency_key=str(payload["idempotency_key"]),
            local_filename=filename,
            expected_bytes=expected_bytes,
            expected_sha256=str(payload["expected_sha256"]),
            gymnast=gymnast,
            kind=str(payload["kind"]),
            recorded_at=recorded_at,
        )
        if upload_request.kind not in MediaAsset.Kind.values:
            raise ValueError("invalid media kind")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", upload_request.expected_sha256):
            raise ValueError("invalid checksum")
        if not upload_request.local_filename:
            raise ValueError("filename is required")
        session, created = open_upload(device.organization, upload_request)
        if created:
            session.device = device
            session.save(update_fields=["device", "updated_at"])
    except (KeyError, TypeError, ValueError, Gymnast.DoesNotExist, json.JSONDecodeError) as error:
        return JsonResponse({"error": "invalid-upload-request", "detail": str(error)}, status=400)
    return JsonResponse(
        {
            "upload_id": str(session.id),
            "state": session.state,
            "received_bytes": session.received_bytes,
            "created": created,
        },
        status=201 if created else 200,
    )


@csrf_exempt
@require_http_methods(["PUT"])
def upload_chunk(request: HttpRequest, upload_id: UUID) -> JsonResponse:
    device = authenticate_device(request)
    if not device:
        return unauthorized()
    session = get_object_or_404(
        UploadSession,
        pk=upload_id,
        organization=device.organization,
        device=device,
    )
    try:
        offset = int(request.headers["X-Upload-Offset"])
        if len(request.body) > settings.WAGVID_MAX_CHUNK_BYTES:
            raise ValueError("chunk too large")
        key = f"uploads/{device.organization_id}/{session.id}.partial"
        received = LocalObjectStore().append_chunk(
            key,
            io.BytesIO(request.body),
            offset=offset,
            max_bytes=settings.WAGVID_MAX_CHUNK_BYTES,
        )
        checkpoint_upload(session.id, received)
    except (KeyError, TypeError, ValueError) as error:
        return JsonResponse({"error": "invalid-upload-chunk", "detail": str(error)}, status=409)
    return JsonResponse({"upload_id": str(session.id), "received_bytes": received})


@csrf_exempt
@require_POST
@transaction.atomic
def upload_finalize(request: HttpRequest, upload_id: UUID) -> JsonResponse:
    device = authenticate_device(request)
    if not device:
        return unauthorized()
    session = get_object_or_404(
        UploadSession.objects.select_for_update(),
        pk=upload_id,
        organization=device.organization,
        device=device,
    )
    if session.state == UploadSession.State.COMPLETED:
        media = MediaAsset.objects.get(
            organization=session.organization, object_key=session.object_key
        )
        return JsonResponse({"media_id": str(media.id), "state": session.state})
    partial_key = f"uploads/{device.organization_id}/{session.id}.partial"
    final_key = f"originals/{device.organization_id}/{session.capture_id}/{session.local_filename}"
    try:
        stored = LocalObjectStore().finalize_partial(
            partial_key,
            final_key,
            expected_size=session.expected_bytes,
            expected_sha256=session.expected_sha256,
        )
    except (FileNotFoundError, ObjectIntegrityError) as error:
        # Verification can be attempted before the final chunk arrives. Keep
        # the resumable session writable instead of forcing a fresh capture.
        session.state = UploadSession.State.UPLOADING
        session.last_error = str(error)
        session.save(update_fields=["state", "last_error", "updated_at"])
        return JsonResponse({"error": "upload-verification-failed"}, status=409)
    media = MediaAsset.objects.create(
        organization=session.organization,
        gymnast=session.gymnast,
        device=device,
        kind=session.kind,
        state=MediaAsset.State.STORED,
        object_key=stored.key,
        sha256=stored.sha256,
        recorded_at=session.recorded_at,
        original_retained=True,
    )
    session.state = UploadSession.State.COMPLETED
    session.received_bytes = stored.size
    session.object_key = stored.key
    session.save(update_fields=["state", "received_bytes", "object_key", "updated_at"])
    session.organization.audit_events.create(
        action="upload.completed",
        object_type="media-asset",
        object_id=str(media.id),
        metadata={"device_id": str(device.id), "capture_id": str(session.capture_id)},
    )
    return JsonResponse({"media_id": str(media.id), "state": session.state}, status=201)
