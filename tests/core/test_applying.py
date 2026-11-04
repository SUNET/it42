import base64
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.core.accounts.models import User
from it42.core.applications.models import ApplicationCopy, ApplicationDraft, StatusChange
from it42.core.catalog.models import PublicGrant
from it42.core.profiles.models import Document

from .conftest import PDF

ANSWERS = {"project_title": "Solar roofs", "budget": "150000"}


def test_profile_needs_login(client: Client, db: None) -> None:
    assert client.get("/profile/").status_code == 302


def test_upload_pdf(u2_client: Client, a2: User) -> None:
    upload = SimpleUploadedFile("cv.pdf", PDF, content_type="application/pdf")
    u2_client.post("/profile/", {"upload": "1", "file": upload})
    doc = Document.objects.get(user=a2)
    assert doc.original_name == "cv.pdf" and doc.size == len(PDF)


@pytest.mark.parametrize(
    "content", [b"GIF89a not a pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024)], ids=["magic", "size"]
)
def test_upload_rejects_non_pdf_and_large_files(
    u2_client: Client, a2: User, content: bytes
) -> None:
    upload = SimpleUploadedFile("x.pdf", content, content_type="application/pdf")
    response = u2_client.post("/profile/", {"upload": "1", "file": upload})
    assert response.status_code == 200
    assert not Document.objects.exists()


def test_cannot_delete_someone_elses_document(
    u2_client: Client, make_user: Callable[..., User], make_document: Callable[..., Document]
) -> None:
    other = make_document(make_user("a1"))
    assert u2_client.post(f"/profile/documents/{other.pk}/delete/").status_code == 404
    assert Document.objects.filter(pk=other.pk).exists()


def apply(client: Client, grant: PublicGrant, **data: Any) -> Any:
    return client.post(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/", {"confirm": "on", **data}
    )


def test_apply_stores_copy_and_queues_event(
    u2_client: Client,
    a2: User,
    make_grant: Callable[..., PublicGrant],
    make_document: Callable[..., Document],
) -> None:
    grant = make_grant("o1")
    doc = make_document(a2)
    response = apply(u2_client, grant, **ANSWERS, documents=[doc.pk])
    application = ApplicationCopy.objects.get()
    assert response["Location"] == f"/my/applications/{application.public_id}/"
    assert application.status == "submitted"
    assert application.documents == [{"name": "cv.pdf", "sha256": doc.sha256}]
    assert StatusChange.objects.get().status == "submitted"

    event = OutboxEvent.objects.get()
    assert (event.exchange, event.type) == ("core-to-o1", "application.submitted")
    assert event.application_id == application.public_id
    assert event.payload["applicant"] == {"subject": "a2", "name": "a2", "email": "a2@kth.se"}
    assert event.payload["answers"] == ANSWERS
    assert base64.b64decode(event.payload["documents"][0]["content"]) == PDF


def test_apply_validates_the_dynamic_form(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    response = apply(u2_client, make_grant(), project_title="", budget="lots")
    assert response.status_code == 200
    assert not ApplicationCopy.objects.exists()


def test_cannot_attach_someone_elses_document(
    u2_client: Client,
    make_user: Callable[..., User],
    make_grant: Callable[..., PublicGrant],
    make_document: Callable[..., Document],
) -> None:
    other = make_document(make_user("a1"))
    response = apply(u2_client, make_grant(), **ANSWERS, documents=[other.pk])
    assert response.status_code == 200
    assert not ApplicationCopy.objects.exists()


def test_one_application_per_grant(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant()
    apply(u2_client, grant, **ANSWERS)
    apply(u2_client, grant, **ANSWERS)
    assert ApplicationCopy.objects.count() == 1
    assert OutboxEvent.objects.count() == 1


def test_closed_grant_cannot_be_applied_to(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    apply(u2_client, make_grant(status="closed"), **ANSWERS)
    assert not ApplicationCopy.objects.exists()


def test_my_applications_shows_only_own(
    u2_client: Client,
    make_user: Callable[..., User],
    make_grant: Callable[..., PublicGrant],
) -> None:
    g1, g2 = make_grant("o1"), make_grant("o2")
    apply(u2_client, g1, **ANSWERS)
    apply(u2_client, g2, **ANSWERS)
    other = Client()
    other.force_login(make_user("a1"))
    body = u2_client.get("/my/applications/").content.decode()
    assert "grant of o1" in body and "grant of o2" in body
    assert "grant of o" not in other.get("/my/applications/").content.decode()
    application = ApplicationCopy.objects.first()
    assert application is not None
    assert other.get(f"/my/applications/{application.public_id}/").status_code == 404
    assert u2_client.get(f"/my/applications/{application.public_id}/").status_code == 200


def received(application: ApplicationCopy, seq: int = 1) -> bytes:
    return Envelope(
        type="application.received",
        payload={"application_id": str(application.public_id), "seq": seq},
        application_id=application.public_id,
        seq=seq,
    ).to_json()


@pytest.fixture
def submitted(u2_client: Client, make_grant: Callable[..., PublicGrant]) -> ApplicationCopy:
    apply(u2_client, make_grant("o1"), **ANSWERS)
    return ApplicationCopy.objects.get()


def test_received_updates_status(submitted: ApplicationCopy) -> None:
    process(received(submitted), "o1-to-core")
    submitted.refresh_from_db()
    assert (submitted.status, submitted.last_seq) == ("received", 1)
    assert list(StatusChange.objects.values_list("status", flat=True)) == [
        "submitted",
        "received",
    ]


def test_other_org_cannot_acknowledge(submitted: ApplicationCopy) -> None:
    with pytest.raises(RejectEvent):
        process(received(submitted), "o2-to-core")
    submitted.refresh_from_db()
    assert submitted.status == "submitted"


def test_unknown_application_is_rejected(db: None) -> None:
    fake = ApplicationCopy(public_id=uuid.uuid4())
    with pytest.raises(RejectEvent):
        process(received(fake), "o1-to-core")


RICH_SCHEMA = [
    {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
    {"name": "applicant_email", "label": "Email address", "type": "email", "required": True},
    {"name": "about", "label": "About the project", "type": "heading"},
    {"name": "intro", "label": "Keep it short.", "type": "paragraph"},
    {
        "name": "area",
        "label": "Area",
        "type": "select",
        "required": True,
        "options": ["Energy", "Water"],
    },
    {"name": "size", "label": "Size", "type": "radio", "options": ["Small", "Large"]},
    {"name": "topics", "label": "Topics", "type": "checkboxes", "options": ["AI", "Bio", "Sea"]},
    {"name": "years", "label": "Years", "type": "integer", "min": 1, "max": 5},
    {"name": "agree", "label": "I agree to the terms", "type": "checkbox", "required": True},
]


def test_apply_form_is_prefilled_and_rendered_from_the_layout(
    u2_client: Client, a2: User, make_grant: Callable[..., PublicGrant]
) -> None:
    from it42.core.profiles.models import Profile

    Profile.objects.create(user=a2, first_name="Oskar", last_name="Bergström")
    grant = make_grant(form_schema=RICH_SCHEMA)
    body = u2_client.get(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/"
    ).content.decode()
    assert 'value="Oskar Bergström"' in body and 'value="a2@kth.se"' in body
    assert '<h2 class="h5 mt-4 mb-2">About the project</h2>' in body
    assert "Keep it short." in body
    assert 'type="radio"' in body and 'class="form-check-input"' in body
    assert "form-select" in body and "<option" in body
    assert body.index("About the project") < body.index("Energy") < body.index("Topics")
    # Layout entries are not inputs.
    assert 'name="about"' not in body and 'name="intro"' not in body


def test_apply_with_every_widget_family(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant(form_schema=RICH_SCHEMA)
    response = apply(
        u2_client,
        grant,
        applicant_name="Oskar",
        applicant_email="oskar@kth.se",
        area="Water",
        size="Large",
        topics=["AI", "Sea"],
        years="3",
        agree="on",
    )
    assert response.status_code == 302
    application = ApplicationCopy.objects.get()
    assert application.answers == {
        "applicant_name": "Oskar",
        "applicant_email": "oskar@kth.se",
        "area": "Water",
        "size": "Large",
        "topics": ["AI", "Sea"],
        "years": 3,
        "agree": True,
    }
    assert OutboxEvent.objects.get().payload["answers"] == application.answers
    body = u2_client.get(f"/my/applications/{application.public_id}/").content.decode()
    assert "AI, Sea" in body and "<dd>Yes</dd>" in body
    assert "About the project" not in body


@pytest.mark.parametrize(
    "bad",
    [
        {"area": "Fire"},
        {"topics": ["AI", "Fire"]},
        {"years": "9"},
        {"agree": ""},
        {"applicant_email": "nope"},
    ],
)
def test_apply_rejects_values_outside_the_schema(
    u2_client: Client, make_grant: Callable[..., PublicGrant], bad: dict[str, Any]
) -> None:
    grant = make_grant(form_schema=RICH_SCHEMA)
    data: dict[str, Any] = {
        "applicant_name": "Oskar",
        "applicant_email": "oskar@kth.se",
        "area": "Water",
        "agree": "on",
        **bad,
    }
    assert apply(u2_client, grant, **data).status_code == 200
    assert not ApplicationCopy.objects.exists()


def test_apply_needs_the_confirmation(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant()
    response = u2_client.post(f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/", ANSWERS)
    assert response.status_code == 200
    assert "Confirm that your application is complete" in response.content.decode()
    assert not ApplicationCopy.objects.exists()


def test_board_puts_applications_in_status_columns(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    for status, grant in (("received", make_grant()), ("approved", make_grant("o2"))):
        apply(u2_client, grant, **ANSWERS)
        ApplicationCopy.objects.filter(grant=grant).update(status=status)
    draft_grant = make_grant(title="Still writing")
    save_draft(u2_client, draft_grant, project_title="Half")
    body = u2_client.get("/my/applications/").content.decode()
    draft, submitted, decision = (
        body.index('id="col-draft"'),
        body.index('id="col-submitted"'),
        body.index('id="col-decision"'),
    )
    assert draft < body.index("Still writing") < submitted
    assert submitted < body.index('data-status="received"') < decision
    assert decision < body.index('data-status="approved"')


def save_draft(client: Client, grant: PublicGrant, **data: Any) -> Any:
    return client.post(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/", {"save_draft": "", **data}
    )


def test_save_draft_keeps_incomplete_answers_and_sends_nothing(
    u2_client: Client, a2: User, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant()
    # Budget is required and must be a number: a draft keeps it anyway, without confirming.
    response = save_draft(u2_client, grant, project_title="Solar roofs", budget="lots")
    assert response.status_code == 302
    draft = ApplicationDraft.objects.get(user=a2, grant=grant)
    assert draft.data["project_title"] == "Solar roofs" and draft.data["budget"] == "lots"
    assert not ApplicationCopy.objects.exists()
    assert not OutboxEvent.objects.exists()
    body = u2_client.get(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/"
    ).content.decode()
    assert 'value="Solar roofs"' in body and 'value="lots"' in body
    assert "Delete draft" in body
    # Saving again updates the same draft.
    save_draft(u2_client, grant, project_title="Solar walls")
    assert ApplicationDraft.objects.get().data["project_title"] == "Solar walls"


def test_submitting_replaces_the_draft(
    u2_client: Client, a2: User, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant()
    save_draft(u2_client, grant, project_title="Solar roofs")
    started = ApplicationDraft.objects.get().created_at
    response = apply(u2_client, grant, **ANSWERS)
    assert response.status_code == 302
    assert not ApplicationDraft.objects.exists()
    application = ApplicationCopy.objects.get()
    assert application.draft_started_at == started
    event = OutboxEvent.objects.get()
    assert "draft_started_at" not in event.payload and "draft" not in str(event.payload)
    body = u2_client.get(f"/my/applications/{application.public_id}/").content.decode()
    assert "Stage 2 of 5" in body


def test_cannot_delete_someone_elses_draft(
    u2_client: Client,
    make_user: Callable[..., User],
    make_grant: Callable[..., PublicGrant],
) -> None:
    other = ApplicationDraft.objects.create(user=make_user("a1"), grant=make_grant(), data={})
    assert u2_client.post(f"/my/drafts/{other.pk}/delete/").status_code == 404
    assert u2_client.get(f"/my/drafts/{other.pk}/delete/").status_code == 405
    assert ApplicationDraft.objects.filter(pk=other.pk).exists()


def test_delete_own_draft(
    u2_client: Client, a2: User, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant()
    save_draft(u2_client, grant, project_title="x")
    draft = ApplicationDraft.objects.get()
    assert u2_client.post(f"/my/drafts/{draft.pk}/delete/").status_code == 302
    assert not ApplicationDraft.objects.exists()


def test_no_draft_for_a_closed_grant(
    u2_client: Client, make_grant: Callable[..., PublicGrant]
) -> None:
    grant = make_grant(status="closed")
    response = save_draft(u2_client, grant, project_title="x")
    assert response.status_code == 302
    assert not ApplicationDraft.objects.exists()
