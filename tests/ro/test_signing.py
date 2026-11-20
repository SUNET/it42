"""Signature requests on the research organisation site (milestone 14)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.common.routing import inbound_queues, sender_of
from it42.ro.signing.models import RequestDocument, SignatureRequest

from .conftest import PDF, requested


def from_org(request: SignatureRequest, type: str, sender: str = "o1", **payload: Any) -> None:
    body = Envelope(
        type=type,
        payload={"application_id": str(request.public_id), **payload},
        application_id=request.public_id,
    ).to_json()
    process(body, f"{sender}-to-ro")


def test_ro_queues_and_sender() -> None:
    assert inbound_queues() == ["o1-to-ro", "o2-to-ro", "o3-to-ro", "o4-to-ro", "o5-to-ro"]
    assert sender_of("o2-to-ro") == "o2"
    assert sender_of("o3-to-ro") == "o3"
    assert sender_of("o4-to-ro") == "o4"
    assert sender_of("o5-to-ro") == "o5"
    for other in ("ro-to-o1", "core-to-o1", "o1-to-core"):
        with pytest.raises(ValueError):
            sender_of(other)


def test_request_is_stored_with_its_documents(kth_request: SignatureRequest) -> None:
    assert (kth_request.org_slug, kth_request.research_org, kth_request.status) == (
        "o1",
        "kth",
        "pending",
    )
    document = RequestDocument.objects.get(request=kth_request)
    with document.file.open("rb") as fh:
        assert fh.read() == PDF


@pytest.mark.parametrize(
    "payload",
    [
        {"research_org": "nowhere"},
        {"form_schema": "not a list"},
        {"deadline": "soon"},
        {"documents": [{"name": "x.pdf", "sha256": "0", "content": "JVBERg=="}]},
    ],
)
def test_invalid_requests_are_rejected(db: None, payload: dict[str, Any]) -> None:
    with pytest.raises(RejectEvent):
        requested("kth", **payload)


def test_a_request_cannot_arrive_twice(kth_request: SignatureRequest) -> None:
    with pytest.raises(RejectEvent):
        requested("kth", app_id=kth_request.public_id)


def test_only_the_asking_org_can_move_or_cancel_a_request(kth_request: SignatureRequest) -> None:
    new = timezone.localdate() + timedelta(days=20)
    with pytest.raises(RejectEvent):
        from_org(kth_request, "signature.deadline_changed", sender="o2", deadline=new.isoformat())
    with pytest.raises(RejectEvent):
        from_org(kth_request, "signature.cancelled", sender="o2", reason="expired")
    from_org(kth_request, "signature.deadline_changed", deadline=new.isoformat())
    kth_request.refresh_from_db()
    assert kth_request.deadline == new
    from_org(kth_request, "signature.cancelled", reason="expired")
    kth_request.refresh_from_db()
    assert kth_request.status == "expired"


def test_board_shows_only_the_members_organisation(
    kth_signer: Client, uu_signer: Client, kth_request: SignatureRequest
) -> None:
    uu_request = requested("uu")
    body = kth_signer.get("/").content.decode()
    assert "Applications from your researchers" in body
    assert f'data-request="{kth_request.public_id}"' in body
    assert f'data-request="{uu_request.public_id}"' not in body
    assert "KTH Royal Institute of Technology" in body
    assert kth_signer.get(f"/requests/{uu_request.pk}/").status_code == 404
    document = RequestDocument.objects.get(request=uu_request)
    assert kth_signer.get(f"/requests/{uu_request.pk}/documents/{document.pk}/").status_code == 404
    assert uu_signer.get(f"/requests/{uu_request.pk}/").status_code == 200


def test_signing_needs_the_confirmation(kth_signer: Client, kth_request: SignatureRequest) -> None:
    kth_signer.post(f"/requests/{kth_request.pk}/sign/", {"comment": "ok"})
    kth_request.refresh_from_db()
    assert kth_request.status == "pending"
    assert not OutboxEvent.objects.exists()


def test_sign_tells_core(kth_signer: Client, kth_request: SignatureRequest) -> None:
    kth_signer.post(f"/requests/{kth_request.pk}/sign/", {"comment": "Fine.", "confirm": "on"})
    kth_request.refresh_from_db()
    assert (kth_request.status, kth_request.comment) == ("signed", "Fine.")
    core_event = OutboxEvent.objects.get(exchange="ro-to-core")
    assert core_event.type == "signature.granted"
    assert core_event.payload == {
        "application_id": str(kth_request.public_id),
        "org_slug": "o1",
        "research_org": "kth",
        "signer": {"name": "sig2", "email": "sig2@kth.se"},
        "signed_at": kth_request.decided_at.isoformat(),
        "comment": "Fine.",
        "method": "click",
    }
    # Decided once: a second click changes nothing.
    kth_signer.post(f"/requests/{kth_request.pk}/decline/", {"reason": "Oops"})
    assert OutboxEvent.objects.count() == 1


def test_decline_needs_a_reason_and_tells_the_org(
    kth_signer: Client, kth_request: SignatureRequest
) -> None:
    kth_signer.post(f"/requests/{kth_request.pk}/decline/", {"reason": ""})
    assert not OutboxEvent.objects.exists()
    kth_signer.post(f"/requests/{kth_request.pk}/decline/", {"reason": "Not employed here."})
    kth_request.refresh_from_db()
    assert kth_request.status == "declined"
    event = OutboxEvent.objects.get(type="signature.declined")
    assert event.exchange == "ro-to-core"
    assert event.payload["reason"] == "Not employed here."


def test_answers_to_the_right_org(kth_signer: Client) -> None:
    request = requested("kth", sender="o2")
    kth_signer.post(f"/requests/{request.pk}/sign/", {"confirm": "on"})
    assert OutboxEvent.objects.get(exchange="ro-to-core").payload["org_slug"] == "o2"


def test_no_signing_after_the_deadline(kth_signer: Client) -> None:
    request = requested("kth", deadline=(timezone.localdate() - timedelta(days=1)).isoformat())
    body = kth_signer.get(f"/requests/{request.pk}/").content.decode()
    assert "data-sign-form" not in body and "The deadline passed" in body
    kth_signer.post(f"/requests/{request.pk}/sign/", {"confirm": "on"})
    request.refresh_from_db()
    assert request.status == "pending" and not OutboxEvent.objects.exists()


def test_detail_shows_the_application(kth_signer: Client, kth_request: SignatureRequest) -> None:
    body = kth_signer.get(f"/requests/{kth_request.pk}/").content.decode()
    assert "Solar research" in body and "Org 1" in body
    assert "Project title" in body and "KTH Royal Institute of Technology" in body
    assert "data-sign-form" in body and "data-decline-form" in body
    document = RequestDocument.objects.get(request=kth_request)
    response = kth_signer.get(f"/requests/{kth_request.pk}/documents/{document.pk}/")
    assert response.status_code == 200


def test_unknown_signature_event_types_are_rejected(db: None) -> None:
    body = Envelope(type="signature.granted", payload={}, application_id=uuid.uuid4()).to_json()
    with pytest.raises(RejectEvent):
        process(body, "o1-to-ro")
