from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    name = "it42.core.applications"
    label = "core_applications"
    verbose_name = "Applications"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 (registers event handlers)
