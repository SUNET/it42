"""The background ORCID import, run by ``manage.py run_orcid_imports`` (``core-orcid``).

A web request only queues an ``OrcidImport``. The runner claims it, fetches and maps the
record, stages the items against the CV (``services.stage_items``) and leaves it in
``review``; nothing is written to the CV here. After every stage it saves ``stage`` and
``progress``, which the loader dialog polls, and stops if the researcher cancelled.
"""

import logging
from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from .models import OrcidImport
from .orcid import OrcidError
from .services import fetch_import, propose_areas, stage_items

log = logging.getLogger(__name__)

Status = OrcidImport.Status

# Stage key -> text of the loader dialog.
STAGES = {
    "queued": "Waiting to start…",
    "connecting": "Connecting to ORCID…",
    "fetching": "Fetching your works and affiliations…",
    "reading": "Reading your publications…",
    "matching": "Matching your CV sections…",
    "preparing": "Getting your data ready to review…",
    "ready": "Ready to review",
}
FAILED = "The import stopped unexpectedly. Please try again."


class Cancelled(Exception):
    """The import is no longer running (cancelled by the researcher)."""


def report(job: OrcidImport, stage: str, progress: int) -> None:
    """Save the stage and progress; raise Cancelled if the import stopped running."""
    updated = OrcidImport.objects.filter(pk=job.pk, status=Status.RUNNING).update(
        stage=stage, progress=progress, updated_at=timezone.now()
    )
    if not updated:
        raise Cancelled


def claim_next() -> OrcidImport | None:
    """Mark the oldest queued import as running and return it."""
    with transaction.atomic():
        job = (
            OrcidImport.objects.select_for_update(skip_locked=True)
            .filter(status=Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        job.status = Status.RUNNING
        job.stage, job.progress = "connecting", 5
        job.save(update_fields=["status", "stage", "progress", "updated_at"])
    return job


def requeue_running() -> int:
    """Put imports a stopped runner left behind back in the queue (run at start-up)."""
    return OrcidImport.objects.filter(status=Status.RUNNING).update(
        status=Status.QUEUED, stage="queued", progress=0
    )


def run(job: OrcidImport, alive: Callable[[], None] = lambda: None) -> None:
    """Fetch, map and stage one claimed import.

    ``alive`` is called with every progress report, so a slow import keeps the
    container's health marker fresh (``run_orcid_imports``).
    """

    def step(stage: str, progress: int) -> None:
        report(job, stage, progress)
        alive()

    try:
        imported = fetch_import(job.orcid, step)
        step("matching", 88)
        items = stage_items(job.profile, imported)
        keywords = propose_areas(job.profile, imported.person)
        step("preparing", 96)
        OrcidImport.objects.filter(pk=job.pk, status=Status.RUNNING).update(
            status=Status.REVIEW,
            stage="ready",
            progress=100,
            orcid=imported.orcid,
            items=items,
            keywords=keywords,
            profile_fields=imported.profile,
            person=imported.person,
            updated_at=timezone.now(),
        )
    except Cancelled:
        return
    except OrcidError as exc:
        fail(job, str(exc))
    except Exception:
        log.exception("ORCID import %s failed", job.public_id)
        fail(job, FAILED)


def fail(job: OrcidImport, message: str) -> None:
    OrcidImport.objects.filter(pk=job.pk, status=Status.RUNNING).update(
        status=Status.FAILED, error=message[:500], finished_at=timezone.now()
    )


def run_pending(alive: Callable[[], None] = lambda: None) -> int:
    """Run every queued import; returns how many ran."""
    count = 0
    while (job := claim_next()) is not None:
        alive()
        run(job, alive)
        count += 1
    return count
