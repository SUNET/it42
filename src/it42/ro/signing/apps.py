from django.apps import AppConfig


class SigningConfig(AppConfig):
    name = "it42.ro.signing"
    label = "ro_signing"
    verbose_name = "Signing"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 (registers event handlers)
