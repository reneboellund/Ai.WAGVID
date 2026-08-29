from django.apps import AppConfig


class WagvidAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wagvid_app"
    verbose_name = "Ai.WAGVID"

    def ready(self) -> None:
        # Keep the very large legacy models.py stable while allowing newer bounded domains to
        # register normal Django models in focused modules.
        from . import membership_invitations  # noqa: F401
