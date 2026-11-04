from django.apps import AppConfig


class MembersConfig(AppConfig):
    name = "it42.org.members"
    label = "org_members"
    verbose_name = "Members"

    def ready(self) -> None:
        from . import signals

        signals.connect()
