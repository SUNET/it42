"""Reviewer actions. Each change that the applicant should see takes the next
per-application sequence number and writes its event in the same transaction.
Review notes are org-internal and never produce an event.

Applications waiting for (or refused) their administrating organisation's signature are
not open for review: no status changes and no questions. ``expire_signatures`` ends the
wait when the grant's signature deadline has passed.
"""

import logging
from calendar import monthrange
from datetime import date, datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from it42.common.outbox import emit
from it42.common.routing import org_to_core, org_to_ro
from it42.common.statuses import ORG_SETTABLE_STATUSES, ApplicationStatus
from it42.org.accounts.models import User

from .models import Application, Question, ReviewNote

logger = logging.getLogger(__name__)


class NotReviewable(ValueError):
    pass


def _check_reviewable(application: Application) -> None:
    if not application.reviewable:
        raise NotReviewable(
            f"This application is {ApplicationStatus(application.status).label.lower()}; "
            "it can be reviewed once its administrating organisation has signed it."
        )


def archive_time(when: datetime) -> datetime:
    """One calendar month later in the site's timezone, clamped to the month's last day."""
    local = timezone.localtime(when, timezone.get_default_timezone())
    year = local.year + (local.month == 12)
    month = local.month % 12 + 1
    return local.replace(year=year, month=month, day=min(local.day, monthrange(year, month)[1]))


def change_status(application_id: int, status: str, actor: User) -> Application:
    if status not in ORG_SETTABLE_STATUSES:
        raise ValueError(f"Status {status!r} cannot be set by an org.")
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        _check_reviewable(application)
        if application.status == status:
            return application
        if status in (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED):
            application.decided_at = timezone.now()
            application.decided_by = actor
            application.archive_at = archive_time(application.decided_at)
        else:
            application.decided_at = None
            application.decided_by = None
            application.archive_at = None
        application.status = status
        seq = application.next_seq()
        application.save(
            update_fields=["status", "decided_at", "decided_by", "archive_at", "seq", "updated_at"]
        )
        emit(
            org_to_core(settings.ORG_SLUG),
            "application.status_changed",
            {"application_id": str(application.public_id), "status": status, "seq": seq},
            application_id=application.public_id,
            seq=seq,
        )
    return application


def ask_question(application_id: int, author: User, text: str) -> Question:
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application_id)
        _check_reviewable(application)
        question = Question.objects.create(application=application, text=text, asked_by=author)
        seq = application.next_seq()
        application.save(update_fields=["seq", "updated_at"])
        emit(
            org_to_core(settings.ORG_SLUG),
            "question.asked",
            {
                "application_id": str(application.public_id),
                "question_id": str(question.public_id),
                "text": text,
                "seq": seq,
            },
            application_id=application.public_id,
            seq=seq,
        )
    return question


def add_note(application_id: int, author: User, text: str) -> ReviewNote:
    return ReviewNote.objects.create(application_id=application_id, author=author, text=text)


def expire_signatures(today: date) -> int:
    """End the wait for every application whose grant's signature deadline is before
    ``today``: it becomes ``ro_expired``, the core hears it and the RO zone withdraws the
    request. Returns how many expired."""
    expired = 0
    pending = Application.objects.filter(
        status=ApplicationStatus.AWAITING_SIGNATURE, grant__signature_deadline__lt=today
    ).values_list("pk", flat=True)
    for pk in pending:
        with transaction.atomic():
            application = Application.objects.select_for_update().get(pk=pk)
            if application.status != ApplicationStatus.AWAITING_SIGNATURE:
                continue
            application.status = ApplicationStatus.RO_EXPIRED
            seq = application.next_seq()
            application.save(update_fields=["status", "seq", "updated_at"])
            emit(
                org_to_core(settings.ORG_SLUG),
                "application.status_changed",
                {
                    "application_id": str(application.public_id),
                    "status": ApplicationStatus.RO_EXPIRED,
                    "seq": seq,
                },
                application_id=application.public_id,
                seq=seq,
            )
            emit(
                org_to_ro(settings.ORG_SLUG),
                "signature.cancelled",
                {"application_id": str(application.public_id), "reason": "expired"},
                application_id=application.public_id,
            )
        expired += 1
        logger.info("signature for %s expired", application.public_id)
    return expired
