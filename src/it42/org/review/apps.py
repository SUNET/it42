from django.apps import AppConfig


class ReviewConfig(AppConfig):
    name = "it42.org.review"
    label = "org_review"
    verbose_name = "Review panels"

    def ready(self) -> None:
        from . import signals

        signals.connect()
