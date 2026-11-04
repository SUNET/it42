import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import close_old_connections

from it42.common.heartbeat import beat
from it42.core.profiles.importer import requeue_running, run_pending


class Command(BaseCommand):
    help = "Run queued ORCID imports in the background (the core-orcid container)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true", help="Run what is queued and exit")
        parser.add_argument(
            "--every", type=float, default=1.0, help="Seconds between looks at the queue"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["once"]:
            # One runner per stack: anything left running was interrupted.
            requeued = requeue_running()
            if requeued:
                self.stdout.write(f"requeued {requeued} interrupted import(s)")
        while True:
            close_old_connections()
            ran = run_pending(alive=lambda: beat("orcid"))
            if ran:
                self.stdout.write(f"ran {ran} ORCID import(s)")
            if options["once"]:
                return
            beat("orcid")
            time.sleep(options["every"])
