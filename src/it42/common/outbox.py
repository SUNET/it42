"""Write events to the transactional outbox."""

import uuid
from typing import Any

from django.db import connection

from .events import Envelope
from .models import OutboxEvent


def emit(
    exchange: str,
    type: str,
    payload: dict[str, Any],
    *,
    version: int = 1,
    application_id: uuid.UUID | None = None,
    grant_id: uuid.UUID | None = None,
    seq: int | None = None,
) -> OutboxEvent:
    """Store an event for ``relay_outbox`` to publish.

    Must run inside the ``transaction.atomic()`` block that makes the state change,
    so the change and its event commit or roll back together.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("emit() must be called inside transaction.atomic()")
    envelope = Envelope(
        type=type,
        version=version,
        payload=payload,
        application_id=application_id,
        grant_id=grant_id,
        seq=seq,
    )
    return OutboxEvent.objects.create(
        id=envelope.id,
        exchange=exchange,
        type=envelope.type,
        version=envelope.version,
        occurred_at=envelope.occurred_at,
        application_id=envelope.application_id,
        grant_id=envelope.grant_id,
        seq=envelope.seq,
        payload=envelope.payload,
    )


def envelope_of(event: OutboxEvent) -> Envelope:
    return Envelope(
        id=event.id,
        type=event.type,
        version=event.version,
        occurred_at=event.occurred_at,
        application_id=event.application_id,
        grant_id=event.grant_id,
        seq=event.seq,
        payload=event.payload,
    )
