from django.contrib import admin

from .models import (
    AnalysisJob,
    AuditEvent,
    Device,
    ExchangeJob,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
)

admin.site.site_header = "Ai.WAGVID systemadministration"
admin.site.site_title = "Ai.WAGVID"

for model in (Organization, Membership, Level, Gymnast, Device, MediaAsset, AnalysisJob, ExchangeJob, AuditEvent):
    admin.site.register(model)
