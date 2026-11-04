from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "it42.core.catalog"
    label = "core_catalog"
    verbose_name = "Catalog"

    def ready(self) -> None:
        from . import handlers  # noqa: F401 (registers event handlers)
