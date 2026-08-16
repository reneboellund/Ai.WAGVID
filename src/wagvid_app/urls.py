from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("", views.dashboard, name="dashboard"),
    path("operate/", views.operate, name="operate"),
    path("gymnasts/", views.gymnasts, name="gymnasts"),
    path("gymnasts/new/", views.gymnast_create, name="gymnast-create"),
    path("devices/", views.devices, name="devices"),
    path("analyses/", views.analyses, name="analyses"),
    path("imports-exports/", views.exchange, name="exchange"),
    path("system/status/", views.system_status, name="system-status"),
]
