from django.urls import path

from . import analysis_api, device_api, media_access, views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("api/device/uploads/open/", device_api.upload_open, name="device-upload-open"),
    path("api/device/pairing/", device_api.pairing_create, name="device-pairing-create"),
    path(
        "api/device/pairing/<uuid:pairing_id>/claim/",
        device_api.pairing_claim,
        name="device-pairing-claim",
    ),
    path("api/device/heartbeat/", device_api.heartbeat, name="device-heartbeat"),
    path("api/device/commands/", device_api.command_poll, name="device-command-poll"),
    path("api/device/capture-context/", device_api.capture_context, name="device-capture-context"),
    path(
        "api/device/commands/<uuid:command_id>/ack/",
        device_api.command_acknowledge,
        name="device-command-ack",
    ),
    path(
        "api/devices/<uuid:device_id>/commands/",
        device_api.command_create,
        name="device-command-create",
    ),
    path("api/analyses/", analysis_api.analyses_create, name="api-analyses-create"),
    path(
        "api/media/<uuid:media_id>/grant/",
        media_access.create_media_grant,
        name="media-object-grant",
    ),
    path(
        "media/<uuid:media_id>/object/",
        media_access.download_media_object,
        name="media-object-download",
    ),
    path(
        "api/analyses/<uuid:analysis_id>/",
        analysis_api.analysis_detail,
        name="api-analysis-detail",
    ),
    path(
        "api/device/uploads/<uuid:upload_id>/chunk/",
        device_api.upload_chunk,
        name="device-upload-chunk",
    ),
    path(
        "api/device/uploads/<uuid:upload_id>/finalize/",
        device_api.upload_finalize,
        name="device-upload-finalize",
    ),
    path("", views.dashboard, name="dashboard"),
    path("operate/", views.operate, name="operate"),
    path("gymnasts/", views.gymnasts, name="gymnasts"),
    path("gymnasts/new/", views.gymnast_create, name="gymnast-create"),
    path("devices/", views.devices, name="devices"),
    path("analyses/", views.analyses, name="analyses"),
    path("analyses/<uuid:job_id>/cancel/", views.analysis_cancel, name="analysis-cancel"),
    path("competitions/", views.competitions, name="competitions"),
    path(
        "competitions/routines/<uuid:routine_id>/kiga.json",
        views.kiga_routine_export,
        name="kiga-routine-export",
    ),
    path("analyses/<uuid:job_id>/review/", views.analysis_review, name="analysis-review"),
    path(
        "analyses/<uuid:job_id>/score-review/",
        views.score_comparison_review,
        name="score-comparison-review",
    ),
    path(
        "analyses/deductions/<uuid:candidate_id>/decision/",
        views.review_decision,
        name="review-decision",
    ),
    path("imports-exports/", views.exchange, name="exchange"),
    path("imports-exports/kiga/preview/", views.kiga_import_preview, name="kiga-import-preview"),
    path("imports-exports/kiga/commit/", views.kiga_import_commit, name="kiga-import-commit"),
    path(
        "imports-exports/gymnasts/commit/",
        views.gymnast_import_commit,
        name="gymnast-import-commit",
    ),
    path("imports-exports/gymnasts.csv", views.gymnast_export, name="gymnast-export"),
    path(
        "imports-exports/reviewed-labels.json",
        views.reviewed_labels_export,
        name="reviewed-labels-export",
    ),
    path(
        "imports-exports/gymnasts/errors.csv",
        views.gymnast_import_errors,
        name="gymnast-import-errors",
    ),
    path("system/status/", views.system_status, name="system-status"),
    path("system/storage/", views.storage_settings, name="storage-settings"),
]
