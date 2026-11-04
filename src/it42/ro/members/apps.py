from django.apps import AppConfig


class MembersConfig(AppConfig):
    name = "it42.ro.members"
    label = "ro_members"
    verbose_name = "Members"

    def ready(self) -> None:
        from . import signals

        signals.connect()
