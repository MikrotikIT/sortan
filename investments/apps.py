from django.apps import AppConfig


class InvestmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "investments"
    verbose_name = "منصة الأفلام"

    def ready(self):
        from . import signals  # noqa: F401
