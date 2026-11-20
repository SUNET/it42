"""Exchange and queue names. Each direction has a direct exchange and a quorum queue
with the same name (rabbitmq/definitions.json).

The core talks to every org (``core-to-o1``, ``o1-to-core``), and every org sends
signature requests to the research organisation zone (``o1-to-ro``). The RO zone sends
its decisions directly to core (``ro-to-core``), which authenticates and relays them to
the requesting org, so an org cannot impersonate an independent research organisation.
"""

from django.conf import settings

# The RO zone's name in exchange names and as a sender.
RO = "ro"


def core_to_org(org_slug: str) -> str:
    return f"core-to-{org_slug}"


def org_to_core(org_slug: str) -> str:
    return f"{org_slug}-to-core"


def org_to_ro(org_slug: str) -> str:
    return f"{org_slug}-to-{RO}"


def ro_to_org(org_slug: str) -> str:
    return f"{RO}-to-{org_slug}"


def ro_to_core() -> str:
    return f"{RO}-to-core"


def inbound_queues() -> list[str]:
    match settings.APP_ROLE:
        case "core":
            return [*(org_to_core(slug) for slug in settings.KNOWN_ORGS), ro_to_core()]
        case "ro":
            return [org_to_ro(slug) for slug in settings.KNOWN_ORGS]
    return [core_to_org(settings.ORG_SLUG), ro_to_org(settings.ORG_SLUG)]


def sender_of(queue: str) -> str:
    """Who sent a message, derived only from its queue: an org slug or "ro" in core, an
    org slug in the RO zone, and "core" or "ro" in an org."""
    match settings.APP_ROLE:
        case "core":
            if queue == ro_to_core():
                return RO
            for slug in settings.KNOWN_ORGS:
                if queue == org_to_core(slug):
                    return slug
        case "ro":
            for slug in settings.KNOWN_ORGS:
                if queue == org_to_ro(slug):
                    return slug
        case _:
            if queue == core_to_org(settings.ORG_SLUG):
                return "core"
            if queue == ro_to_org(settings.ORG_SLUG):
                return RO
    raise ValueError(f"unexpected queue {queue!r}")
