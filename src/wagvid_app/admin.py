from django.contrib import admin

from .models import (
    AnalysisJob,
    AnalysisResult,
    AuditEvent,
    DeductionCandidate,
    Device,
    Event,
    ExchangeJob,
    ExternalMediaReference,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    OfficialResultSnapshot,
    Organization,
    ReviewDecision,
    Routine,
    SystemAlert,
    UploadSession,
    WorkerNode,
)

admin.site.site_header = "Ai.WAGVID systemadministration"
admin.site.site_title = "Ai.WAGVID"

for model in (
    Organization,
    Membership,
    Level,
    Gymnast,
    Device,
    MediaAsset,
    AnalysisJob,
    AnalysisResult,
    DeductionCandidate,
    ReviewDecision,
    Event,
    Routine,
    ExternalMediaReference,
    OfficialResultSnapshot,
    ExchangeJob,
    AuditEvent,
    UploadSession,
    WorkerNode,
    SystemAlert,
):
    admin.site.register(model)
