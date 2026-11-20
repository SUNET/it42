"""The org's side of the administrating organisation's sign-off (milestone 14)."""

import base64
import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.formschema import BASE_FIELDS
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.org.applications import services
from it42.org.applications.models import Application
from it42.org.grants import services as grant_services
from it42.org.grants.models import SIGNATURE_DAYS, Grant
from it42.org.review.models import Panel

PDF = b"%PDF-1.4\n%%EOF\n"
SCHEMA = [
    *BASE_FIELDS,
    {"name": "project_title", "label": "Project title", "type": "text", "required": True},
]


@pytest.fixture
def grant(make_user: Callable[..., Any]) -> Grant:
    return Grant.objects.create(
        title="g1",
        description="d",
        deadline=timezone.localdate() + timedelta(days=30),
        form_schema=SCHEMA,
        status=Grant.Status.PUBLISHED,
        created_by=make_user("creator"),
    )


def submitted(grant: Grant, org: str = "kth", app_id: uuid.UUID | None = None) -> bytes:
    app_id = app_id or uuid.uuid4()
    return Envelope(
        type="application.submitted",
        payload={
            "application_id": str(app_id),
            "grant_public_id": str(grant.public_id),
            "applicant": {"subject": "a2", "name": "Oskar Bergström", "email": "o@kth.se"},
            "answers": {
                "applicant_name": "Oskar Bergström",
                "applicant_email": "o@kth.se",
                "administrating_organisation": org,
                "project_title": "Solar",
            },
            "submitted_at": timezone.now().isoformat(),
            "documents": [
                {
                    "name": "cv.pdf",
                    "sha256": hashlib.sha256(PDF).hexdigest(),
                    "content": base64.b64encode(PDF).decode(),
                }
            ],
        },
        application_id=app_id,
        grant_id=grant.public_id,
    ).to_json()


def from_ro(application: Application, type: str, **payload: Any) -> bytes:
    return Envelope(
        type=type,
        payload={"application_id": str(application.public_id), **payload},
        application_id=application.public_id,
    ).to_json()


SIGNER = {"name": "Nils Hedlund", "email": "nils.hedlund@kth.se"}


@pytest.fixture
def waiting(grant: Grant) -> Application:
    process(submitted(grant), "core-to-o1")
    return Application.objects.get()


def test_new_grants_give_organisations_a_week_after_the_deadline(grant: Grant) -> None:
    assert grant.signature_deadline == grant.deadline + timedelta(days=SIGNATURE_DAYS)


def test_application_naming_an_organisation_waits_and_is_sent_for_signing(
    waiting: Application, grant: Grant
) -> None:
    assert (waiting.status, waiting.research_org) == ("awaiting_signature", "kth")
    received = OutboxEvent.objects.get(type="application.received")
    assert (received.exchange, received.payload["awaiting_signature"]) == ("o1-to-core", True)
    request = OutboxEvent.objects.get(type="signature.requested")
    assert request.exchange == "o1-to-ro"
    assert request.payload["research_org"] == "kth"
    assert request.payload["deadline"] == grant.signature_deadline.isoformat()
    assert request.payload["form_schema"] == grant.form_schema
    assert request.payload["documents"][0]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert base64.b64decode(request.payload["documents"][0]["content"]) == PDF


def test_without_an_organisation_the_application_goes_straight_to_review(
    make_user: Callable[..., Any],
) -> None:
    schema = [{**f, "required": False} if f["type"] == "research_org" else f for f in SCHEMA]
    grant = Grant.objects.create(
        title="g2",
        description="d",
        deadline=timezone.localdate() + timedelta(days=30),
        form_schema=schema,
        status=Grant.Status.PUBLISHED,
        created_by=make_user("creator"),
    )
    process(submitted(grant, org=""), "core-to-o1")
    assert Application.objects.get().status == "received"
    assert not OutboxEvent.objects.filter(type="signature.requested").exists()
    assert "awaiting_signature" not in OutboxEvent.objects.get(type="application.received").payload


@pytest.mark.parametrize("org", ["nowhere", "UU"])
def test_unknown_organisation_is_rejected(grant: Grant, org: str) -> None:
    with pytest.raises(RejectEvent):
        process(submitted(grant, org=org), "core-to-o1")


def test_the_ro_zone_cannot_submit_applications(grant: Grant) -> None:
    with pytest.raises(RejectEvent):
        process(submitted(grant), "ro-to-o1")
    assert not Application.objects.exists()


def test_signature_opens_the_application_for_review(waiting: Application) -> None:
    signed_at = timezone.now()
    process(
        from_ro(
            waiting,
            "signature.granted",
            signer=SIGNER,
            signed_at=signed_at.isoformat(),
            comment="Fine by us.",
            method="click",
        ),
        "core-to-o1",
    )
    waiting.refresh_from_db()
    assert (waiting.status, waiting.signed_by, waiting.signature_note) == (
        "received",
        "Nils Hedlund",
        "Fine by us.",
    )
    assert waiting.seq == 1
    assert not OutboxEvent.objects.filter(type="application.status_changed").exists()


def test_only_core_can_relay_an_ro_decision(waiting: Application) -> None:
    with pytest.raises(RejectEvent):
        process(from_ro(waiting, "signature.granted", signer=SIGNER), "ro-to-o1")
    waiting.refresh_from_db()
    assert waiting.status == "awaiting_signature"


def test_decline_ends_the_application_with_the_reason(waiting: Application) -> None:
    process(
        from_ro(waiting, "signature.declined", signer=SIGNER, reason="Not employed here."),
        "core-to-o1",
    )
    waiting.refresh_from_db()
    assert (waiting.status, waiting.signature_note) == ("ro_declined", "Not employed here.")
    assert waiting.seq == 1
    assert not OutboxEvent.objects.filter(type="application.status_changed").exists()


def test_decline_needs_a_reason(waiting: Application) -> None:
    with pytest.raises(RejectEvent):
        process(from_ro(waiting, "signature.declined", signer=SIGNER, reason=""), "core-to-o1")


def test_signature_for_an_unknown_application_is_rejected(db: None) -> None:
    body = Envelope(
        type="signature.granted",
        payload={"signer": SIGNER},
        application_id=uuid.uuid4(),
    ).to_json()
    with pytest.raises(RejectEvent):
        process(body, "core-to-o1")


def test_core_decision_reconciles_a_locally_expired_application(
    waiting: Application, grant: Grant
) -> None:
    assert services.expire_signatures(grant.signature_deadline) == 0
    assert services.expire_signatures(grant.signature_deadline + timedelta(days=1)) == 1
    waiting.refresh_from_db()
    assert waiting.status == "ro_expired"
    cancelled = OutboxEvent.objects.get(type="signature.cancelled")
    assert (cancelled.exchange, cancelled.payload["reason"]) == ("o1-to-ro", "expired")
    assert (
        OutboxEvent.objects.get(type="application.status_changed").payload["status"] == "ro_expired"
    )
    # Core accepted the decision before the expiry reached it, so its relay wins and
    # brings the org back into agreement with core.
    before = OutboxEvent.objects.count()
    process(from_ro(waiting, "signature.granted", signer=SIGNER), "core-to-o1")
    waiting.refresh_from_db()
    assert waiting.status == "received" and OutboxEvent.objects.count() == before


def test_moving_the_signature_deadline_updates_open_requests(
    waiting: Application, grant: Grant
) -> None:
    new = grant.signature_deadline + timedelta(days=10)
    assert grant_services.set_signature_deadline(grant.pk, new) == 1
    changed = OutboxEvent.objects.get(type="signature.deadline_changed")
    assert (changed.exchange, changed.payload["deadline"]) == ("o1-to-ro", new.isoformat())
    with pytest.raises(grant_services.InvalidTransition):
        grant_services.set_signature_deadline(grant.pk, grant.deadline - timedelta(days=1))


def test_admin_moves_the_deadline_from_the_grant_page(
    admin_client: Client, waiting: Application, grant: Grant
) -> None:
    new = grant.signature_deadline + timedelta(days=3)
    page = admin_client.get(f"/grants/{grant.pk}/applications/").content.decode()
    assert "Signature deadline" in page and "KTH Royal Institute of Technology" in page
    admin_client.post(
        f"/grants/{grant.pk}/signature-deadline/", {"signature_deadline": new.isoformat()}
    )
    grant.refresh_from_db()
    assert grant.signature_deadline == new


def test_members_cannot_move_the_deadline(member_client: Client, grant: Grant) -> None:
    response = member_client.post(
        f"/grants/{grant.pk}/signature-deadline/", {"signature_deadline": "2099-01-01"}
    )
    assert response.status_code == 403


def test_unsigned_applications_cannot_be_reviewed(
    waiting: Application, make_user: Callable[..., Any], admin_client: Client
) -> None:
    with pytest.raises(services.NotReviewable):
        services.change_status(waiting.pk, "under_review", make_user("member"))
    with pytest.raises(services.NotReviewable):
        services.ask_question(waiting.pk, make_user("staff2"), "Why?")
    panel = Panel.objects.create(name="P", created_by=make_user("chair"))
    panel.grants.add(waiting.grant)
    assert not panel.applications().exists()
    body = admin_client.get(f"/applications/{waiting.pk}/").content.decode()
    assert 'data-signoff="awaiting_signature"' in body
    assert "Set the status" not in body and "Send to applicant" not in body
    assert "Awaiting signature" in admin_client.get("/").content.decode()
