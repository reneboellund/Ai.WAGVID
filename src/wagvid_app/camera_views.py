"""Organization-scoped network camera setup and operator actions."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .camera_operations import (
    CameraOperationError,
    apply_capability_snapshot,
    camera_action,
    require_camera_operator,
)
from .forms import NetworkCameraForm
from .models import NetworkCamera
from .organization_context import active_organization


def _can_control(request, organization):
    try:
        require_camera_operator(request.user, organization)
    except PermissionError:
        return False
    return True


@login_required
def camera_list(request):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/cameras.html",
        {
            "organization": organization,
            "cameras": organization.network_cameras.prefetch_related("actions"),
            "can_control": _can_control(request, organization),
        },
    )


@login_required
def camera_edit(request, camera_id=None):
    organization = active_organization(request)
    if not organization or not _can_control(request, organization):
        return HttpResponseForbidden()
    camera = (
        get_object_or_404(NetworkCamera, pk=camera_id, organization=organization)
        if camera_id
        else NetworkCamera(organization=organization)
    )
    initial = {"capability_json": camera.capability_snapshot or None}
    form = NetworkCameraForm(request.POST or None, instance=camera, initial=initial)
    if request.method == "POST" and form.is_valid():
        value = form.save(commit=False)
        value.organization = organization
        try:
            apply_capability_snapshot(value, form.cleaned_data.get("capability_json") or {})
        except CameraOperationError as error:
            form.add_error("capability_json", str(error))
        else:
            value.save()
            organization.audit_events.create(
                actor=request.user,
                action="camera.updated" if camera_id else "camera.created",
                object_type="network-camera",
                object_id=str(value.id),
                metadata={"capability_digest": value.capability_digest},
            )
            messages.success(request, "IP-kameraets opsætning er gemt uden plaintext credentials.")
            return redirect("camera-detail", camera_id=value.id)
    return render(
        request,
        "wagvid/camera_form.html",
        {"organization": organization, "form": form, "camera": camera if camera_id else None},
    )


@login_required
def camera_detail(request, camera_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    camera = get_object_or_404(NetworkCamera, pk=camera_id, organization=organization)
    return render(
        request,
        "wagvid/camera_detail.html",
        {
            "organization": organization,
            "camera": camera,
            "streams": camera.capability_snapshot.get("streams", []),
            "events": camera.capability_snapshot.get("events", []),
            "can_control": _can_control(request, organization),
            "tracking_modes": NetworkCamera.TrackingMode.choices,
        },
    )


@login_required
@require_POST
def camera_control(request, camera_id):
    organization = active_organization(request)
    if not organization:
        return HttpResponseForbidden()
    camera = get_object_or_404(NetworkCamera, pk=camera_id, organization=organization)
    action = request.POST.get("action", "")
    payload = {
        "mode": request.POST.get("mode", ""),
        "preset_id": request.POST.get("preset_id", ""),
    }
    try:
        result = camera_action(camera=camera, actor=request.user, action=action, payload=payload)
    except PermissionError:
        return HttpResponseForbidden()
    except CameraOperationError as error:
        messages.error(request, str(error))
    else:
        if result.result == "failed":
            messages.error(request, result.message)
        else:
            messages.success(request, f"Kamerahandlingen {action} er registreret og auditeret.")
    return redirect("camera-detail", camera_id=camera.id)
