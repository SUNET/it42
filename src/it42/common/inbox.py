"""Consume events exactly once: dedupe on the event id, dispatch on (type, version)."""

import logging
from collections.abc import Callable

from django.db import IntegrityError, transaction

from .events import Envelope, RejectEvent
from .models import ProcessedEvent
from .routing import sender_of

logger = logging.getLogger(__name__)

# handler(envelope, sender) where sender is an org slug (in the core and the RO zone) or
# "core" / "ro" (in an org); see routing.sender_of.
Handler = Callable[[Envelope, str], None]
_HANDLERS: dict[tuple[str, int], Handler] = {}


def handler(type: str, version: int = 1) -> Callable[[Handler], Handler]:
    def register(func: Handler) -> Handler:
        key = (type, version)
        if key in _HANDLERS:
            raise RuntimeError(f"duplicate handler for {key}")
        _HANDLERS[key] = func
        return func

    return register


def process(body: bytes, queue: str) -> bool:
    """Apply one message. Returns False if it was a duplicate.

    Raises RejectEvent for messages that must be dead-lettered, and any other
    exception for failures worth retrying.
    """
    envelope = Envelope.from_json(body)
    sender = sender_of(queue)
    func = _HANDLERS.get((envelope.type, envelope.version))
    if func is None:
        raise RejectEvent(f"no handler for {envelope.type} v{envelope.version}")
    with transaction.atomic():
        try:
            with transaction.atomic():
                ProcessedEvent.objects.create(event_id=envelope.id, type=envelope.type, queue=queue)
        except IntegrityError:
            logger.info("skipping duplicate event %s (%s)", envelope.id, envelope.type)
            return False
        func(envelope, sender)
    logger.info("processed %s %s from %s", envelope.type, envelope.id, sender)
    return True
