"""Application events from the core, and signature events from the research
organisation (RO) zone.

The sender comes from the arrival queue (``routing.sender_of``): "core" or "ro". Each
handler accepts only its own sender, so the RO zone can never submit an application or
answer a question, and the core can never sign.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from django import forms
from django.conf import settings
from django.core.files.base import ContentFile

from it42.common import research_orgs
from it42.common.documents import decode_documents, encode_documents
from it42.common.events import Envelope, RejectEvent
from it42.common.formschema import SchemaError, build_form, research_org_of
from it42.common.inbox import handler
from it42.common.outbox import emit
from it42.common.routing import RO, org_to_core, org_to_ro
from it42.common.statuses import ApplicationStatus
from it42.org.grants.models import Grant

from .models import Application, ApplicationDocument, Question

logger = logging.getLogger(__name__)


def _require_sender(envelope: Envelope, sender: str, expected: str) -> None:
    if sender != expected:
        raise RejectEvent(f"{envelope.type} must come from {expected}, not {sender}")


def _string(value: object, name: str, max_length: int, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise RejectEvent(f"{name} must be a string of at most {max_length} characters")
    return value.strip()


def _answers(grant: Grant, answers: object) -> dict[str, Any]:
    if not isinstance(answers, dict):
        raise RejectEvent("answers must be an object")
    try:
        form = build_form(grant.form_schema, forms.Form)(data=answers)
    except SchemaError as exc:
        raise RejectEvent(f"grant has an invalid schema: {exc}") from exc
    if not form.is_valid() or set(answers) - set(form.fields):
        raise RejectEvent(f"answers do not fit the grant's form: {form.errors.as_json()}")
    return answers


@handler("application.submitted")
def on_submitted(envelope: Envelope, sender: str) -> None:
    _require_sender(envelope, sender, "core")
    payload = envelope.payload
    if envelope.application_id is None or envelope.grant_id is None:
        raise RejectEvent("application.submitted needs application_id and grant_id")
    grant = Grant.objects.filter(public_id=envelope.grant_id, status=Grant.Status.PUBLISHED).first()
    if grant is None:
        raise RejectEvent(f"grant {envelope.grant_id} is not a published grant of this org")
    if Application.objects.filter(public_id=envelope.application_id).exists():
        raise RejectEvent(f"application {envelope.application_id} already exists")
    applicant = payload.get("applicant")
    if not isinstance(applicant, dict):
        raise RejectEvent("applicant is required")
    answers = _answers(grant, payload.get("answers"))
    research_org = research_org_of(grant.form_schema, answers)
    if research_org:
        org = research_orgs.get(research_org)
        if org is None or not org.active:
            raise RejectEvent(f"{research_org!r} is not an active research organisation")
    documents = decode_documents(payload.get("documents", []))
    try:
        submitted_at = datetime.fromisoformat(payload["submitted_at"])
    except (KeyError, TypeError, ValueError):
        submitted_at = envelope.occurred_at

    application = Application.objects.create(
        public_id=envelope.application_id,
        grant=grant,
        applicant_subject=_string(applicant.get("subject"), "applicant subject", 255),
        applicant_name=_string(applicant.get("name"), "applicant name", 200),
        applicant_email=_string(applicant.get("email", ""), "email", 254, required=False),
        answers=answers,
        research_org=research_org,
        status=(
            ApplicationStatus.AWAITING_SIGNATURE if research_org else ApplicationStatus.RECEIVED
        ),
        submitted_at=submitted_at,
    )
    for name, sha256, content in documents:
        document = ApplicationDocument(
            application=application, original_name=name, sha256=sha256, size=len(content)
        )
        document.file.save(name, ContentFile(content), save=True)
    seq = application.next_seq()
    application.save(update_fields=["seq"])
    received: dict[str, Any] = {"application_id": str(application.public_id), "seq": seq}
    if research_org:
        received["awaiting_signature"] = True
    emit(
        org_to_core(settings.ORG_SLUG),
        "application.received",
        received,
        application_id=application.public_id,
        seq=seq,
    )
    if research_org:
        # The organisation signs what the org holds: the same answers and PDFs.
        emit(
            org_to_ro(settings.ORG_SLUG),
            "signature.requested",
            {
                "application_id": str(application.public_id),
                "grant_public_id": str(grant.public_id),
                "grant_title": grant.title,
                "research_org": research_org,
                "applicant": {
                    "subject": application.applicant_subject,
                    "name": application.applicant_name,
                    "email": application.applicant_email,
                },
                "answers": answers,
                "form_schema": grant.form_schema,
                "submitted_at": submitted_at.isoformat(),
                "deadline": grant.signature_deadline.isoformat(),
                "documents": encode_documents(documents),
            },
            application_id=application.public_id,
            grant_id=grant.public_id,
        )


@handler("question.answered")
def on_question_answered(envelope: Envelope, sender: str) -> None:
    _require_sender(envelope, sender, "core")
    question = (
        Question.objects.select_for_update()
        .filter(
            public_id=envelope.payload.get("question_id"),
            application__public_id=envelope.application_id,
        )
        .first()
        if _is_uuid(envelope.payload.get("question_id"))
        else None
    )
    if question is None:
        raise RejectEvent("no such question for this application")
    if question.answered_at is not None:
        logger.info("question %s is already answered; ignoring", question.public_id)
        return
    question.answer = _string(envelope.payload.get("answer"), "answer", 5000)
    question.answered_at = envelope.occurred_at
    question.save(update_fields=["answer", "answered_at"])


def _awaiting(envelope: Envelope, sender: str) -> Application | None:
    """The application a signature event is about, locked; None (and the event is
    acknowledged and dropped) when it no longer waits for a signature, for example a late
    answer after the org let it expire."""
    _require_sender(envelope, sender, RO)
    application = (
        Application.objects.select_for_update().filter(public_id=envelope.application_id).first()
        if envelope.application_id
        else None
    )
    if application is None or not application.research_org:
        raise RejectEvent(f"no application {envelope.application_id} waits for a signature")
    if application.status != ApplicationStatus.AWAITING_SIGNATURE:
        logger.info(
            "ignoring %s for %s: it is %s", envelope.type, application.public_id, application.status
        )
        return None
    return application


def _signer(payload: dict[str, Any]) -> tuple[str, str]:
    signer = payload.get("signer")
    if not isinstance(signer, dict):
        raise RejectEvent("signer is required")
    return (
        _string(signer.get("name"), "signer name", 200),
        _string(signer.get("email", ""), "signer email", 254, required=False),
    )


def _when(value: object, envelope: Envelope) -> datetime:
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return envelope.occurred_at
    return when if when.tzinfo else envelope.occurred_at


def _decide(
    application: Application,
    status: str,
    signer: tuple[str, str],
    when: datetime,
    note: str,
    extra: dict[str, Any],
) -> None:
    application.status = status
    application.signed_by, application.signed_by_email = signer
    application.signed_at = when
    application.signature_note = note
    seq = application.next_seq()
    application.save()
    emit(
        org_to_core(settings.ORG_SLUG),
        "application.status_changed",
        {"application_id": str(application.public_id), "status": status, "seq": seq, **extra},
        application_id=application.public_id,
        seq=seq,
    )


@handler("signature.granted")
def on_signature_granted(envelope: Envelope, sender: str) -> None:
    application = _awaiting(envelope, sender)
    if application is None:
        return
    payload = envelope.payload
    signer = _signer(payload)
    comment = _string(payload.get("comment", ""), "comment", 2000, required=False)
    signed_at = _when(payload.get("signed_at"), envelope)
    _decide(
        application,
        ApplicationStatus.RECEIVED,
        signer,
        signed_at,
        comment,
        {
            "signature": {
                "research_org": application.research_org,
                "signer_name": signer[0],
                "signed_at": signed_at.isoformat(),
            }
        },
    )


@handler("signature.declined")
def on_signature_declined(envelope: Envelope, sender: str) -> None:
    application = _awaiting(envelope, sender)
    if application is None:
        return
    payload = envelope.payload
    reason = _string(payload.get("reason"), "reason", 2000)
    _decide(
        application,
        ApplicationStatus.RO_DECLINED,
        _signer(payload),
        _when(payload.get("declined_at"), envelope),
        reason,
        {"reason": reason},
    )


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
