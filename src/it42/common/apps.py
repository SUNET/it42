from typing import Any

from django.apps import AppConfig
from django.core import checks


class CommonConfig(AppConfig):
    name = "it42.common"
    label = "common"
    verbose_name = "IT42 common"

    def ready(self) -> None:
        from . import system_handlers  # noqa: F401 (registers event handlers)

        checks.register(check_research_orgs)


def check_research_orgs(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """The RO directory must load: every zone reads it (migrate runs this at start)."""
    from . import research_orgs

    try:
        research_orgs.directory()
    except research_orgs.DirectoryError as exc:
        return [checks.Error(f"RESEARCH_ORGS_FILE: {exc}", id="it42.E001")]
    return []
