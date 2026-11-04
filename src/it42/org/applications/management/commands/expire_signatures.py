import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections
from django.utils import timezone

from it42.org.applications.services import expire_signatures


class Command(BaseCommand):
    help = "Expire applications whose administrating organisation did not sign in time."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--every", type=int, default=0, help="Repeat every N seconds (the worker uses 60)"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            close_old_connections()
            expired = expire_signatures(timezone.localdate())
            if expired:
                self.stdout.write(f"expired {expired} signature request(s)")
            if not options["every"]:
                return
            time.sleep(options["every"])
