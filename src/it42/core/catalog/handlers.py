"""Grant events from orgs."""

from datetime import date, time
from typing import Any

from django.conf import settings

from it42.common.events import Envelope, RejectEvent
from it42.common.formschema import SchemaError, validate_schema
from it42.common.inbox import handler

from .models import PublicGrant


def _text(payload: dict[str, Any], key: str, max_length: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise RejectEvent(f"{key} must be a non-empty string of at most {max_length} characters")
    return value.strip()


@handler("grant.published")
def on_grant_published(envelope: Envelope, sender: str) -> None:
    if envelope.grant_id is None:
        raise RejectEvent("grant.published needs grant_id")
    payload = envelope.payload
    try:
        deadline = date.fromisoformat(payload["deadline"])
        # Added later to the payload; older orgs send none and close at the end of the day.
        raw_time = payload.get("deadline_time")
        deadline_time = time.fromisoformat(raw_time) if raw_time else None
        form_schema = validate_schema(payload.get("form_schema", []))
    except (KeyError, TypeError, ValueError, SchemaError) as exc:
        raise RejectEvent(f"invalid grant: {exc}") from exc
    PublicGrant.objects.update_or_create(
        org_slug=sender,
        grant_public_id=envelope.grant_id,
        defaults={
            # The sender is known from the queue; never trust a name in the payload.
            "org_name": settings.KNOWN_ORGS[sender],
            "title": _text(payload, "title", 200),
            "description": _text(payload, "description", 20_000),
            "deadline": deadline,
            "deadline_time": deadline_time,
            "form_schema": form_schema,
            "status": PublicGrant.Status.OPEN,
        },
    )


@handler("grant.closed")
def on_grant_closed(envelope: Envelope, sender: str) -> None:
    updated = PublicGrant.objects.filter(org_slug=sender, grant_public_id=envelope.grant_id).update(
        status=PublicGrant.Status.CLOSED
    )
    if not updated:
        raise RejectEvent(f"{sender} has no grant {envelope.grant_id}")
