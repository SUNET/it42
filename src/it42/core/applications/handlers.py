"""Application events from orgs and signing decisions from the RO zone.

Every handler first loads the application by id *and* the sending org, so an org
can never touch another org's applications. Status and question events carry a
per-application sequence number; anything at or below ``last_seq`` is stale. Signing
and decline decisions arrive directly from the RO broker identity so a funding org
cannot forge the independent decision.
"""

import logging
import uuid
from datetime import datetime

from it42.common import research_orgs
from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import handler
from it42.common.outbox import emit
from it42.common.routing import RO, core_to_org
from it42.common.statuses import (
    NOT_REVIEWABLE,
    ORG_SETTABLE_STATUSES,
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
    if envelope.seq != 1:
        raise RejectEvent("application.received must be the org's first event")
    if awaiting != bool(application.research_org):
        raise RejectEvent("application.received does not match the administrating organisation")
    if _is_fresh(application, envelope):
        status = ApplicationStatus.AWAITING_SIGNATURE if awaiting else ApplicationStatus.RECEIVED
        _set_status(application, status, envelope)


def _text(value: object, name: str, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise RejectEvent(f"{name} must be a string of at most {max_length} characters")
    return value.strip()


def _required_text(value: object, name: str, max_length: int) -> str:
    text = _text(value, name, max_length)
    if not text:
        raise RejectEvent(f"{name} is required")
    return text


def _signer(payload: dict) -> dict[str, str]:
    signer = payload.get("signer")
    if not isinstance(signer, dict):
        raise RejectEvent("signer is required")
    return {
        "name": _required_text(signer.get("name"), "signer name", 200),
        "email": _text(signer.get("email", ""), "signer email", 254),
    }


def _when(payload: dict, name: str) -> datetime:
    try:
        return datetime.fromisoformat(str(payload.get(name)))
    except ValueError as exc:
        raise RejectEvent(f"{name} must be an ISO date and time") from exc


def _ro_application(envelope: Envelope, sender: str) -> ApplicationCopy:
    if sender != RO:
        raise RejectEvent(f"{envelope.type} must come directly from {RO}, not {sender}")
    if envelope.application_id is None:
        raise RejectEvent(f"{envelope.type} needs application_id")
    org_slug = envelope.payload.get("org_slug")
    if not isinstance(org_slug, str):
        raise RejectEvent("org_slug is required")
    application = (
        ApplicationCopy.objects.select_for_update()
        .filter(public_id=envelope.application_id, org_slug=org_slug)
        .first()
    )
    if application is None:
        raise RejectEvent(f"{org_slug} has no application {envelope.application_id}")
    if envelope.payload.get("research_org") != application.research_org:
        raise RejectEvent("decision is from a different organisation than the applicant named")
    if not application.research_org:
        raise RejectEvent("a signing decision needs an administrating organisation")
    if application.status not in (
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.AWAITING_SIGNATURE,
    ):
        raise RejectEvent(f"{application.public_id} is not waiting for a signature")
    return application


def _record_ro_status(
    application: ApplicationCopy, status: str, envelope: Envelope, update_fields: list[str]
) -> None:
    application.status = status
    # application.received is the org's sequence 1. A fast RO decision may overtake it
    # on the separate queue; reserving 1 prevents that older acknowledgement from
    # reverting the independently authenticated decision.
    application.last_seq = max(application.last_seq, 1)
    application.save(update_fields=[*update_fields, "status", "last_seq", "updated_at"])
    StatusChange.objects.create(
        application=application,
        status=status,
        seq=application.last_seq,
        changed_at=envelope.occurred_at,
    )


@handler("signature.granted")
def on_signature_granted(envelope: Envelope, sender: str) -> None:
    application = _ro_application(envelope, sender)
    signer = _signer(envelope.payload)
    application.signed_by = signer["name"]
    application.signed_at = _when(envelope.payload, "signed_at")
    application.decline_reason = ""
    _record_ro_status(
        application,
        ApplicationStatus.RECEIVED,
        envelope,
        ["signed_by", "signed_at", "decline_reason"],
    )
    emit(
        core_to_org(application.org_slug),
        "signature.granted",
        {
            "application_id": str(application.public_id),
            "signer": signer,
            "signed_at": application.signed_at.isoformat(),
            "comment": _text(envelope.payload.get("comment", ""), "comment", 2000),
            "method": _required_text(envelope.payload.get("method"), "method", 50),
        },
        application_id=application.public_id,
    )
    logger.info(
        "%s signed by %s",
        application.public_id,
        research_orgs.name_of(application.research_org),
    )


@handler("signature.declined")
def on_signature_declined(envelope: Envelope, sender: str) -> None:
    application = _ro_application(envelope, sender)
    signer = _signer(envelope.payload)
    declined_at = _when(envelope.payload, "declined_at")
    application.decline_reason = _required_text(envelope.payload.get("reason"), "reason", 2000)
    _record_ro_status(
        application,
        ApplicationStatus.RO_DECLINED,
        envelope,
        ["decline_reason"],
    )
    emit(
        core_to_org(application.org_slug),
        "signature.declined",
        {
            "application_id": str(application.public_id),
            "signer": signer,
            "declined_at": declined_at.isoformat(),
            "reason": application.decline_reason,
        },
        application_id=application.public_id,
    )
    logger.info(
        "%s declined by %s",
        application.public_id,
        research_orgs.name_of(application.research_org),
    )


@handler("application.status_changed")
def on_status_changed(envelope: Envelope, sender: str) -> None:
    application = _application_of(envelope, sender)
    status = envelope.payload.get("status")
    if status in (ApplicationStatus.RECEIVED, ApplicationStatus.RO_DECLINED):
        raise RejectEvent(f"{status!r} must come directly from {RO}")
    if status == ApplicationStatus.RO_EXPIRED:
        # The funding org owns the signature deadline and may expire a pending request.
        if not application.research_org:
            raise RejectEvent(f"{status!r} needs an administrating organisation")
        if not _is_fresh(application, envelope):
            return
        if application.status not in (
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.AWAITING_SIGNATURE,
        ):
            raise RejectEvent(f"{application.public_id} is not waiting for a signature")
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
