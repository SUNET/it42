from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from it42.common.outbox import emit
from it42.common.routing import core_to_org, org_to_core, org_to_ro, ro_to_org


class Command(BaseCommand):
    help = "Queue a system.ping; the other side answers with system.pong."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--org", help="Target org (core and RO zone only)")
        parser.add_argument(
            "--to-ro", action="store_true", help="Ping the RO zone instead of the core (orgs)"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.APP_ROLE in ("core", "ro"):
            org = options["org"]
            if org not in settings.KNOWN_ORGS:
                raise CommandError(f"--org must be one of {', '.join(settings.KNOWN_ORGS)}")
            exchange = core_to_org(org) if settings.APP_ROLE == "core" else ro_to_org(org)
        elif options["to_ro"]:
            exchange = org_to_ro(settings.ORG_SLUG)
        else:
            exchange = org_to_core(settings.ORG_SLUG)
        with transaction.atomic():
            event = emit(exchange, "system.ping", {})
        self.stdout.write(f"queued system.ping {event.id} on {exchange}")
