"""Signature events from the orgs.

The sending org comes only from the arrival queue (``o1-to-ro``); every later event about
a request must come from the org that sent it.
"""

import logging
import uuid
from datetime import date, datetime

from django.core.files.base import ContentFile

from it42.common import research_orgs
from it42.common.documents import decode_documents
from it42.common.events import Envelope, RejectEvent
from it42.common.formschema import SchemaError, validate_schema
from it42.common.inbox import handler

from .models import RequestDocument, SignatureRequest

logger = logging.getLogger(__name__)


def _string(value: object, name: str, max_length: int, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > max_length or (required and not value.strip()):
        raise RejectEvent(f"{name} must be a string of at most {max_length} characters")
    return value.strip()


def _date(value: object, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RejectEvent(f"{name} must be an ISO date") from exc


@handler("signature.requested")
def on_requested(envelope: Envelope, sender: str) -> None:
    payload = envelope.payload
    if envelope.application_id is None or envelope.grant_id is None:
        raise RejectEvent("signature.requested needs application_id and grant_id")
    if SignatureRequest.objects.filter(public_id=envelope.application_id).exists():
        raise RejectEvent(f"a request for {envelope.application_id} already exists")
    slug = payload.get("research_org")
    if not isinstance(slug, str) or research_orgs.get(slug) is None:
        raise RejectEvent(f"{slug!r} is not in the research organisation directory")
    applicant = payload.get("applicant")
    if not isinstance(applicant, dict):
        raise RejectEvent("applicant is required")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise RejectEvent("answers must be an object")
    try:
        schema = validate_schema(payload.get("form_schema"))
    except SchemaError as exc:
        raise RejectEvent(f"invalid form_schema: {exc}") from exc
    documents = decode_documents(payload.get("documents", []))
    try:
        submitted_at = datetime.fromisoformat(str(payload.get("submitted_at")))
    except ValueError:
        submitted_at = envelope.occurred_at
    request = SignatureRequest.objects.create(
        public_id=envelope.application_id,
        org_slug=sender,
        research_org=slug,
        grant_public_id=envelope.grant_id,
        grant_title=_string(payload.get("grant_title"), "grant_title", 200),
        applicant_subject=_string(applicant.get("subject"), "applicant subject", 255),
        applicant_name=_string(applicant.get("name"), "applicant name", 200),
        applicant_email=_string(applicant.get("email", ""), "email", 254, required=False),
        answers=answers,
        form_schema=schema,
        submitted_at=submitted_at,
        deadline=_date(payload.get("deadline"), "deadline"),
    )
    for name, sha256, content in documents:
        document = RequestDocument(
            request=request, original_name=name, sha256=sha256, size=len(content)
        )
        document.file.save(name, ContentFile(content), save=True)


def _request_of(envelope: Envelope, sender: str) -> SignatureRequest:
    """The request, locked, if the sending org owns it; RejectEvent otherwise."""
    try:
        public_id = uuid.UUID(str(envelope.application_id))
    except ValueError as exc:
        raise RejectEvent(f"{envelope.type} needs application_id") from exc
    request = (
        SignatureRequest.objects.select_for_update()
        .filter(public_id=public_id, org_slug=sender)
        .first()
    )
    if request is None:
        raise RejectEvent(f"{sender} has no signature request {public_id}")
    return request


@handler("signature.deadline_changed")
def on_deadline_changed(envelope: Envelope, sender: str) -> None:
    request = _request_of(envelope, sender)
    deadline = _date(envelope.payload.get("deadline"), "deadline")
    if request.status != SignatureRequest.Status.PENDING:
        logger.info("ignoring new deadline for %s: it is %s", request.public_id, request.status)
        return
    request.deadline = deadline
    request.save(update_fields=["deadline", "updated_at"])


@handler("signature.cancelled")
def on_cancelled(envelope: Envelope, sender: str) -> None:
    request = _request_of(envelope, sender)
    if request.status != SignatureRequest.Status.PENDING:
        logger.info("ignoring cancellation of %s: it is %s", request.public_id, request.status)
        return
    request.status = SignatureRequest.Status.EXPIRED
    request.save(update_fields=["status", "updated_at"])
