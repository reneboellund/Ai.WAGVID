from dataclasses import dataclass
from shutil import disk_usage

from django.conf import settings
from django.db import connection

from .models import AnalysisJob, SystemAlert, WorkerNode


@dataclass(frozen=True)
class RuntimeProbe:
    name: str
    status: str
    detail: str


def probe_database() -> RuntimeProbe:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return RuntimeProbe("database", "ok", "query succeeded")


def probe_object_storage() -> RuntimeProbe:
    root = settings.WAGVID_OBJECT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    free = disk_usage(root).free
    status = "ok" if free >= settings.WAGVID_MIN_FREE_BYTES else "attention"
    return RuntimeProbe("object-storage", status, f"{free} free bytes")


def probe_workers() -> RuntimeProbe:
    online = WorkerNode.objects.filter(state=WorkerNode.State.ONLINE).count()
    waiting = AnalysisJob.objects.filter(state=AnalysisJob.State.QUEUED).count()
    status = "ok" if online or not waiting else "degraded"
    return RuntimeProbe("workers", status, f"{online} online, {waiting} queued")


def runtime_probes() -> list[RuntimeProbe]:
    return [probe_database(), probe_object_storage(), probe_workers()]


def sync_runtime_alerts() -> list[SystemAlert]:
    alerts = []
    for probe in runtime_probes():
        code = f"runtime.{probe.name}"
        if probe.status == "ok":
            SystemAlert.objects.filter(code=code, active=True).update(active=False)
            continue
        alert, _ = SystemAlert.objects.update_or_create(
            code=code,
            active=True,
            defaults={
                "severity": (
                    SystemAlert.Severity.CRITICAL
                    if probe.status == "degraded"
                    else SystemAlert.Severity.WARNING
                ),
                "message": probe.detail,
            },
        )
        alerts.append(alert)
    return alerts
