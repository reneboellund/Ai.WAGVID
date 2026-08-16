from django.urls import path

from . import device_api, views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("api/device/uploads/open/", device_api.upload_open, name="device-upload-open"),
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
    path("analyses/<uuid:job_id>/review/", views.analysis_review, name="analysis-review"),
    path(
        "analyses/deductions/<uuid:candidate_id>/decision/",
        views.review_decision,
        name="review-decision",
    ),
    path("imports-exports/", views.exchange, name="exchange"),
    path(
        "imports-exports/gymnasts/commit/",
        views.gymnast_import_commit,
        name="gymnast-import-commit",
    ),
    path("imports-exports/gymnasts.csv", views.gymnast_export, name="gymnast-export"),
    path("system/status/", views.system_status, name="system-status"),
]
