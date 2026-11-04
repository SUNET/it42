"""Application events from orgs.

Every handler first loads the application by id *and* the sending org, so an org
can never touch another org's applications. Status and question events carry a
per-application sequence number; anything at or below ``last_seq`` is stale.
"""

import logging
import uuid
from datetime import datetime

from it42.common import research_orgs
from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import handler
from it42.common.statuses import (
    NOT_REVIEWABLE,
    ORG_SETTABLE_STATUSES,
    SIGNING_OUTCOMES,
    ApplicationStatus,
)

from .models import ApplicationCopy, QuestionCopy, StatusChange

logger = logging.getLogger(__name__)


def _application_of(envelope: Envelope, sender: str) -> ApplicationCopy:
    if envelope.application_id is None or envelope.seq is None:
        raise RejectEvent(f"{envelope.type} needs application_id and seq")
    application = (
        ApplicationCopy.objects.select_for_update()
        .filter(public_id=envelope.application_id, org_slug=sender)
        .first()
    )
    if application is None:
        raise RejectEvent(f"{sender} has no application {envelope.application_id}")
    return application


def _is_fresh(application: ApplicationCopy, envelope: Envelope) -> bool:
    assert envelope.seq is not None  # noqa: S101 (checked by _application_of)
    if envelope.seq <= application.last_seq:
        logger.info(
            "ignoring stale %s seq %s (last %s) for %s",
            envelope.type,
            envelope.seq,
            application.last_seq,
            application.public_id,
        )
        return False
    return True


def _set_status(application: ApplicationCopy, status: str, envelope: Envelope) -> None:
    assert envelope.seq is not None  # noqa: S101
    application.status = status
    application.last_seq = envelope.seq
    application.save(update_fields=["status", "last_seq", "updated_at"])
    StatusChange.objects.create(
        application=application, status=status, seq=envelope.seq, changed_at=envelope.occurred_at
    )


@handler("application.received")
def on_received(envelope: Envelope, sender: str) -> None:
    application = _application_of(envelope, sender)
    awaiting = envelope.payload.get("awaiting_signature", False) is True
    if awaiting and not application.research_org:
        raise RejectEvent("the applicant named no administrating organisation")
    if _is_fresh(application, envelope):
        status = ApplicationStatus.AWAITING_SIGNATURE if awaiting else ApplicationStatus.RECEIVED
        _set_status(application, status, envelope)


def _text(value: object, name: str, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise RejectEvent(f"{name} must be a string of at most {max_length} characters")
    return value.strip()


def _record_signoff(application: ApplicationCopy, status: str, payload: dict) -> None:
    """Keep what the org reported about the organisation's decision."""
    if status == ApplicationStatus.RECEIVED:
        signature = payload.get("signature")
        if not isinstance(signature, dict):
            raise RejectEvent("a signed application needs its signature")
        if signature.get("research_org") != application.research_org:
            raise RejectEvent("signed by a different organisation than the applicant named")
        application.signed_by = _text(signature.get("signer_name"), "signer_name", 200)
        try:
            application.signed_at = datetime.fromisoformat(str(signature.get("signed_at")))
        except ValueError as exc:
            raise RejectEvent("signed_at must be an ISO date and time") from exc
    elif status == ApplicationStatus.RO_DECLINED:
        application.decline_reason = _text(payload.get("reason", ""), "reason", 2000)


@handler("application.status_changed")
def on_status_changed(envelope: Envelope, sender: str) -> None:
    application = _application_of(envelope, sender)
    status = envelope.payload.get("status")
    if status in SIGNING_OUTCOMES:
        # Only the end of a sign-off; the org's own staff cannot set these.
        if not application.research_org:
            raise RejectEvent(f"{status!r} needs an administrating organisation")
        if not _is_fresh(application, envelope):
            return
        if application.status not in (
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.AWAITING_SIGNATURE,
        ):
            raise RejectEvent(f"{application.public_id} is not waiting for a signature")
        _record_signoff(application, status, envelope.payload)
        application.save(update_fields=["signed_by", "signed_at", "decline_reason"])
        _set_status(application, status, envelope)
        logger.info(
            "%s by %s: %s",
            application.public_id,
            research_orgs.name_of(application.research_org),
            status,
        )
        return
    if status not in ORG_SETTABLE_STATUSES:
        raise RejectEvent(f"an org cannot set status {status!r}")
    if not _is_fresh(application, envelope):
        return
    if application.status in NOT_REVIEWABLE:
        raise RejectEvent(f"{application.public_id} has not been signed")
    _set_status(application, status, envelope)


@handler("question.asked")
def on_question_asked(envelope: Envelope, sender: str) -> None:
    application = _application_of(envelope, sender)
    text = envelope.payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 5000:
        raise RejectEvent("question text must be 1-5000 characters")
    try:
        question_id = uuid.UUID(str(envelope.payload.get("question_id")))
    except ValueError as exc:
        raise RejectEvent("question_id must be a UUID") from exc
    if not _is_fresh(application, envelope):
        return
    if application.status in NOT_REVIEWABLE:
        raise RejectEvent(f"{application.public_id} has not been signed")
    if QuestionCopy.objects.filter(question_public_id=question_id).exists():
        raise RejectEvent(f"question {question_id} already exists")
    QuestionCopy.objects.create(
        application=application,
        question_public_id=question_id,
        text=text.strip(),
        asked_at=envelope.occurred_at,
    )
    assert envelope.seq is not None  # noqa: S101
    application.last_seq = envelope.seq
    application.save(update_fields=["last_seq", "updated_at"])
