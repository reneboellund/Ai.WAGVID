"""Runtime maintenance guard for operator and API writes."""

from django.http import JsonResponse

from .models import MaintenanceState


class MaintenanceReadOnlyMiddleware:
    safe_methods = {"GET", "HEAD", "OPTIONS"}
    exempt_prefixes = ("/health/", "/ready/", "/system/updates/", "/admin/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in self.safe_methods and not request.path.startswith(
            self.exempt_prefixes
        ):
            state = MaintenanceState.objects.filter(pk=1, active=True, read_only=True).first()
            if state:
                return JsonResponse(
                    {
                        "error": "maintenance-read-only",
                        "detail": state.reason or "Systemet er midlertidigt skrivebeskyttet.",
                    },
                    status=503,
                )
        return self.get_response(request)
