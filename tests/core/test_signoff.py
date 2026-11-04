"""The applicant's side of the administrating organisation's sign-off (milestone 14)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.formschema import BASE_FIELDS
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.core.applications.models import ApplicationCopy
from it42.core.catalog.models import PublicGrant

SCHEMA = [
    *BASE_FIELDS,
    {"name": "project_title", "label": "Project title", "type": "text", "required": True},
]
ANSWERS = {
    "applicant_name": "Oskar",
    "applicant_email": "a2@kth.se",
    "administrating_organisation": "kth",
    "project_title": "Solar",
}


def apply(client: Client, grant: PublicGrant, **data: Any) -> Any:
    return client.post(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/", {"confirm": "on", **data}
    )


def event(application: ApplicationCopy, type: str, seq: int, **payload: Any) -> bytes:
    return Envelope(
        type=type,
        payload={"application_id": str(application.public_id), "seq": seq, **payload},
        application_id=application.public_id,
        seq=seq,
    ).to_json()


@pytest.fixture
def grant(make_grant: Callable[..., PublicGrant]) -> PublicGrant:
    return make_grant("o1", form_schema=SCHEMA)


@pytest.fixture
def application(u2_client: Client, grant: PublicGrant) -> ApplicationCopy:
    apply(u2_client, grant, **ANSWERS)
    application = ApplicationCopy.objects.get()
    process(event(application, "application.received", 1, awaiting_signature=True), "o1-to-core")
    application.refresh_from_db()
    return application


def test_apply_form_offers_the_organisations_as_a_search_box(
    u2_client: Client, grant: PublicGrant
) -> None:
    body = u2_client.get(f"/grants/o1/{grant.grant_public_id}/apply/").content.decode()
    assert 'data-combobox="true"' in body and "it42/combobox.js" in body
    assert "KTH Royal Institute of Technology" in body and 'value="uu"' in body


def test_submit_keeps_the_chosen_organisation(application: ApplicationCopy) -> None:
    assert application.research_org == "kth"
    assert application.status == "awaiting_signature"
    submitted = OutboxEvent.objects.get(type="application.submitted")
    assert submitted.payload["answers"]["administrating_organisation"] == "kth"


@pytest.mark.parametrize("org", ["", "nowhere"])
def test_a_required_organisation_must_be_a_known_one(
    u2_client: Client, grant: PublicGrant, org: str
) -> None:
    apply(u2_client, grant, **{**ANSWERS, "administrating_organisation": org})
    assert not ApplicationCopy.objects.exists()


def test_an_optional_organisation_may_be_left_empty(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    schema = [{**f, "required": False} if f["type"] == "research_org" else f for f in SCHEMA]
    apply(
        u2_client,
        make_grant("o1", form_schema=schema),
        **{**ANSWERS, "administrating_organisation": ""},
    )
    assert ApplicationCopy.objects.get().research_org == ""


def test_signed_application_shows_the_signer(
    u2_client: Client, application: ApplicationCopy
) -> None:
    signed_at = timezone.now()
    process(
        event(
            application,
            "application.status_changed",
            2,
            status="received",
            signature={
                "research_org": "kth",
                "signer_name": "Nils Hedlund",
                "signed_at": signed_at.isoformat(),
            },
        ),
        "o1-to-core",
    )
    application.refresh_from_db()
    assert (application.status, application.signed_by) == ("received", "Nils Hedlund")
    body = u2_client.get(f"/my/applications/{application.public_id}/").content.decode()
    assert "Signed by Nils Hedlund for KTH Royal Institute of Technology" in body


def test_a_signature_for_another_organisation_is_rejected(application: ApplicationCopy) -> None:
    body = event(
        application,
        "application.status_changed",
        2,
        status="received",
        signature={
            "research_org": "uu",
            "signer_name": "x",
            "signed_at": "2026-10-20T10:00:00+00:00",
        },
    )
    with pytest.raises(RejectEvent):
        process(body, "o1-to-core")


def test_review_statuses_wait_for_the_signature(application: ApplicationCopy) -> None:
    with pytest.raises(RejectEvent):
        process(
            event(application, "application.status_changed", 2, status="under_review"), "o1-to-core"
        )
    application.refresh_from_db()
    assert application.status == "awaiting_signature"


def test_declined_application_shows_the_reason_and_can_be_sent_again(
    u2_client: Client, grant: PublicGrant, application: ApplicationCopy
) -> None:
    process(
        event(
            application,
            "application.status_changed",
            2,
            status="ro_declined",
            reason="Not employed here.",
        ),
        "o1-to-core",
    )
    application.refresh_from_db()
    assert (application.status, application.decline_reason) == ("ro_declined", "Not employed here.")
    body = u2_client.get(f"/my/applications/{application.public_id}/").content.decode()
    assert "Not employed here." in body and "You can apply again" in body
    # The grant page offers to apply again, and a second application goes through.
    detail = u2_client.get(f"/grants/o1/{grant.grant_public_id}/").content.decode()
    assert "View your application" not in detail
    apply(u2_client, grant, **{**ANSWERS, "administrating_organisation": "uu"})
    assert ApplicationCopy.objects.count() == 2
    assert ApplicationCopy.objects.exclude(pk=application.pk).get().research_org == "uu"


def test_expired_application_can_be_sent_again(
    u2_client: Client, grant: PublicGrant, application: ApplicationCopy
) -> None:
    process(event(application, "application.status_changed", 2, status="ro_expired"), "o1-to-core")
    application.refresh_from_db()
    assert application.status == "ro_expired"
    apply(u2_client, grant, **ANSWERS)
    assert ApplicationCopy.objects.count() == 2


def test_a_live_application_still_blocks_a_second_one(
    u2_client: Client, grant: PublicGrant, application: ApplicationCopy
) -> None:
    apply(u2_client, grant, **ANSWERS)
    assert ApplicationCopy.objects.count() == 1


def test_signing_statuses_need_an_organisation(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    schema = [{**f, "required": False} if f["type"] == "research_org" else f for f in SCHEMA]
    apply(
        u2_client,
        make_grant("o1", form_schema=schema),
        **{**ANSWERS, "administrating_organisation": ""},
    )
    application = ApplicationCopy.objects.get()
    with pytest.raises(RejectEvent):
        process(
            event(application, "application.received", 1, awaiting_signature=True), "o1-to-core"
        )
    with pytest.raises(RejectEvent):
        process(
            event(application, "application.status_changed", 1, status="ro_declined", reason="x"),
            "o1-to-core",
        )
