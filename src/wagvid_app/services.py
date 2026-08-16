from dataclasses import dataclass

from django.db.models import Q

from .models import AnalysisJob, Device, MediaAsset, Organization


@dataclass(frozen=True)
class DashboardStatus:
    health: str
    device_attention: int
    upload_backlog: int
    analysis_backlog: int
    review_backlog: int


def dashboard_status(organization: Organization) -> DashboardStatus:
    device_attention = organization.devices.filter(Q(state=Device.State.OFFLINE) | Q(queued_uploads__gt=0)).count()
    upload_backlog = organization.media.exclude(state=MediaAsset.State.STORED).count()
    analysis_backlog = organization.analysis_jobs.filter(state__in=[AnalysisJob.State.QUEUED, AnalysisJob.State.RUNNING, AnalysisJob.State.BLOCKED]).count()
    review_backlog = organization.analysis_jobs.filter(state=AnalysisJob.State.NEEDS_REVIEW).count()
    health = "attention" if any((device_attention, upload_backlog, analysis_backlog, review_backlog)) else "healthy"
    return DashboardStatus(health, device_attention, upload_backlog, analysis_backlog, review_backlog)
