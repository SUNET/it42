"""system.ping / system.pong: a round trip that proves the messaging path works."""

import logging

from django.conf import settings

from .events import Envelope
from .inbox import handler
from .outbox import emit
from .routing import RO, core_to_org, org_to_core, org_to_ro, ro_to_org

logger = logging.getLogger(__name__)


def reply_exchange(sender: str) -> str:
    match settings.APP_ROLE:
        case "core":
            return core_to_org(sender)
        case "ro":
            return ro_to_org(sender)
    return org_to_ro(settings.ORG_SLUG) if sender == RO else org_to_core(settings.ORG_SLUG)


@handler("system.ping")
def on_ping(envelope: Envelope, sender: str) -> None:
    emit(reply_exchange(sender), "system.pong", {"ping_id": str(envelope.id)})


@handler("system.pong")
def on_pong(envelope: Envelope, sender: str) -> None:
    logger.info("pong from %s for ping %s", sender, envelope.payload.get("ping_id"))
