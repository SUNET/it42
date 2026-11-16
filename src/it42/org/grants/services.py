"""Grant state changes. Each one writes its event to the outbox in the same transaction."""

from datetime import date

from django.conf import settings
from django.db import transaction

from it42.common.formschema import (
    SchemaError,
    require_base_fields,
    require_publishable,
    validate_schema,
)
from it42.common.outbox import emit
from it42.common.routing import org_to_core, org_to_ro
from it42.common.statuses import ApplicationStatus
from it42.org.applications.models import Application

from .models import Grant


class InvalidTransition(Exception):
    pass


def publish(grant_id: int) -> Grant:
    with transaction.atomic():
        grant = Grant.objects.select_for_update().get(pk=grant_id)
        if grant.status != Grant.Status.DRAFT:
            raise InvalidTransition("Only drafts can be published.")
        try:
            schema = validate_schema(grant.form_schema)
            require_base_fields(schema)
            require_publishable(schema)
        except SchemaError as exc:
            raise InvalidTransition(f"The application form is not complete: {exc}") from exc
        grant.status = Grant.Status.PUBLISHED
        grant.save(update_fields=["status", "updated_at"])
        emit(
            org_to_core(settings.ORG_SLUG),
            "grant.published",
            {
                "grant_public_id": str(grant.public_id),
                "org_name": settings.ORG_NAME,
                "title": grant.title,
                "description": grant.description,
                "deadline": grant.deadline.isoformat(),
                # Added after the first release; core treats a missing time as end of day.
                "deadline_time": grant.deadline_time.strftime("%H:%M"),
                "form_schema": grant.form_schema,
            },
            grant_id=grant.public_id,
        )
    return grant


def close(grant_id: int) -> Grant:
    with transaction.atomic():
        grant = Grant.objects.select_for_update().get(pk=grant_id)
        if grant.status != Grant.Status.PUBLISHED:
            raise InvalidTransition("Only published grants can be closed.")
        grant.status = Grant.Status.CLOSED
        grant.save(update_fields=["status", "updated_at"])
        emit(
            org_to_core(settings.ORG_SLUG),
            "grant.closed",
            {"grant_public_id": str(grant.public_id)},
            grant_id=grant.public_id,
        )
    return grant


def set_signature_deadline(grant_id: int, deadline: date) -> int:
    """Move the last day organisations can sign this grant's applications (allowed at any
    time, also after the call closed). Every open request is updated on the RO site.
    Returns how many open requests were told."""
    with transaction.atomic():
        grant = Grant.objects.select_for_update().get(pk=grant_id)
        if deadline < grant.deadline:
            raise InvalidTransition("Organisations cannot be asked to sign before the call closes.")
        if deadline == grant.signature_deadline:
            return 0
        grant.signature_deadline = deadline
        grant.save(update_fields=["signature_deadline", "updated_at"])
        waiting = Application.objects.filter(
            grant=grant, status=ApplicationStatus.AWAITING_SIGNATURE
        )
        for application in waiting:
            emit(
                org_to_ro(settings.ORG_SLUG),
                "signature.deadline_changed",
                {"application_id": str(application.public_id), "deadline": deadline.isoformat()},
                application_id=application.public_id,
            )
        return len(waiting)
