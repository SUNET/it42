"""Public call transitions publish outbox events. Board actions stay within the organisation."""

from datetime import date
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

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
from it42.org.review.models import Panel

from .board import DECISIONS
from .models import BoardNote, Category, Grant


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


def _board_id(value: str) -> int:
    """Parse a positive BigAutoField key from a card or tag control."""
    field = forms.IntegerField(min_value=1, max_value=(1 << 63) - 1)
    try:
        return field.clean(value)
    except ValidationError as exc:
        raise ValueError("Unknown board item.") from exc


@transaction.atomic
def change_board_items(
    keys: list[str], action: str, *, owner_id: int, is_admin: bool, text: str = "", tag: str = ""
) -> None:
    """Apply a selection together, locking targets before checking their current state."""
    if action not in {"archive", "pause", "resume", "note", "tag"}:
        raise ValueError("Choose a board action.")
    if action in {"pause", "resume", "tag"} and not is_admin:
        raise PermissionDenied("Only organisation admins can manage calls.")
    if not keys:
        raise ValueError("Select at least one card.")
    targets: dict[str, set[int]] = {"grant": set(), "application": set(), "panel": set()}
    for key in keys:
        kind, _, value = key.partition(":")
        if kind not in targets:
            raise ValueError("Unknown board item.")
        targets[kind].add(_board_id(value))
    if len(text) > 2000:
        raise ValueError("Use at most 2000 characters for a note.")
    for kind, model in (("grant", Grant), ("application", Application), ("panel", Panel)):
        ids = targets[kind]
        if not ids:
            continue
        rows = list(model.objects.filter(pk__in=ids).order_by("pk").select_for_update())
        if len(rows) != len(ids):
            raise ValueError("A selected card no longer exists.")
        if action == "note":
            for item in rows:
                target: dict[str, Any] = {kind: item}
                if text:
                    BoardNote.objects.update_or_create(
                        owner_id=owner_id, **target, defaults={"text": text}
                    )
                else:
                    BoardNote.objects.filter(owner_id=owner_id, **target).delete()
        elif action == "archive":
            if kind != "application" or any(
                not isinstance(item, Application) or item.status not in DECISIONS for item in rows
            ):
                raise ValueError("Only accepted or declined applications can be archived.")
            now = timezone.now()
            # Preserve the original archive time on retries. Archiving is local to this org.
            Application.objects.filter(pk__in=ids).exclude(archive_at__lte=now).update(
                archive_at=now
            )
        elif kind != "grant":
            raise ValueError("Select only calls for this action.")
        elif action == "tag":
            category = None
            if tag:
                category = Category.objects.select_for_update().filter(pk=_board_id(tag)).first()
                if category is None:
                    raise ValueError("Choose an existing call tag.")
            Grant.objects.filter(pk__in=ids).update(category=category, updated_at=timezone.now())
        else:
            paused = action == "pause"
            Grant.objects.filter(pk__in=ids).exclude(board_paused=paused).update(
                board_paused=paused, updated_at=timezone.now()
            )
