import base64
import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.org.applications.models import Application, ApplicationDocument
from it42.org.grants.models import Grant

PDF = b"%PDF-1.4\n%%EOF\n"
SCHEMA = [
    {"name": "project_title", "label": "Project title", "type": "text", "required": True},
    {"name": "budget", "label": "Budget", "type": "number", "required": True},
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


def submitted(grant_id: uuid.UUID, app_id: uuid.UUID | None = None, **payload: Any) -> bytes:
    app_id = app_id or uuid.uuid4()
    body: dict[str, Any] = {
        "application_id": str(app_id),
        "grant_public_id": str(grant_id),
        "applicant": {"subject": "a2", "name": "Oskar Bergström", "email": "o@kth.se"},
        "answers": {"project_title": "Solar", "budget": "1500"},
        "submitted_at": timezone.now().isoformat(),
        "documents": [
            {
                "name": "cv.pdf",
                "sha256": hashlib.sha256(PDF).hexdigest(),
                "content": base64.b64encode(PDF).decode(),
            }
        ],
    }
    body.update(payload)
    return Envelope(
        type="application.submitted", payload=body, application_id=app_id, grant_id=grant_id
    ).to_json()


def test_submitted_creates_application_and_replies(grant: Grant) -> None:
    process(submitted(grant.public_id), "core-to-o1")
    application = Application.objects.get()
    assert (application.applicant_subject, application.status, application.seq) == (
        "a2",
        "received",
        1,
    )
    document = ApplicationDocument.objects.get()
    assert document.file.read() == PDF
    reply = OutboxEvent.objects.get()
    assert (reply.exchange, reply.type, reply.seq) == ("o1-to-core", "application.received", 1)
    assert reply.application_id == application.public_id


def test_unpublished_or_foreign_grant_is_rejected(grant: Grant) -> None:
    with pytest.raises(RejectEvent):
        process(submitted(uuid.uuid4()), "core-to-o1")
    grant.status = Grant.Status.CLOSED
    grant.save()
    with pytest.raises(RejectEvent):
        process(submitted(grant.public_id), "core-to-o1")
    assert not Application.objects.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"answers": {"project_title": "", "budget": "1500"}},
        {"answers": {"project_title": "x", "budget": "1", "extra": "y"}},
        {
            "documents": [
                {"name": "cv.pdf", "sha256": "0" * 64, "content": base64.b64encode(PDF).decode()}
            ]
        },
        {
            "documents": [
                {"name": "x.pdf", "sha256": "", "content": base64.b64encode(b"GIF89a").decode()}
            ]
        },
        {"documents": [{"name": "x.pdf", "sha256": "", "content": "!!!"}]},
        {"applicant": "a2"},
    ],
)
def test_invalid_applications_are_rejected(grant: Grant, payload: dict[str, Any]) -> None:
    with pytest.raises(RejectEvent):
        process(submitted(grant.public_id, **payload), "core-to-o1")
    assert not Application.objects.exists()
    assert not OutboxEvent.objects.exists()


def test_same_application_id_twice_is_rejected(grant: Grant) -> None:
    app_id = uuid.uuid4()
    process(submitted(grant.public_id, app_id), "core-to-o1")
    with pytest.raises(RejectEvent):
        process(submitted(grant.public_id, app_id), "core-to-o1")
    assert Application.objects.count() == 1


RICH_SCHEMA = [
    {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
    {"name": "applicant_email", "label": "Email address", "type": "email", "required": True},
    {"name": "about", "label": "About the project", "type": "heading"},
    {"name": "area", "label": "Area", "type": "select", "options": ["Energy", "Water"]},
    {"name": "topics", "label": "Topics", "type": "checkboxes", "options": ["AI", "Bio"]},
    {"name": "years", "label": "Years", "type": "integer", "min": 1, "max": 5},
    {"name": "agree", "label": "I agree", "type": "checkbox", "required": True},
]
RICH_ANSWERS: dict[str, Any] = {
    "applicant_name": "Oskar",
    "applicant_email": "o@kth.se",
    "area": "Water",
    "topics": ["AI", "Bio"],
    "years": 3,
    "agree": True,
}


@pytest.fixture
def rich_grant(grant: Grant) -> Grant:
    grant.form_schema = RICH_SCHEMA
    grant.save()
    return grant


def test_list_and_boolean_answers_are_accepted(rich_grant: Grant, admin_client: Any) -> None:
    process(submitted(rich_grant.public_id, answers=RICH_ANSWERS), "core-to-o1")
    application = Application.objects.get()
    assert application.answers == RICH_ANSWERS
    body = admin_client.get(f"/applications/{application.pk}/").content.decode()
    assert "AI, Bio" in body and "<dd>Yes</dd>" in body


@pytest.mark.parametrize(
    "bad",
    [
        {"area": "Fire"},
        {"topics": ["AI", "Fire"]},
        {"topics": "AI"},
        {"years": 9},
        {"years": "three"},
        {"agree": None},
        {"about": "not an input"},
    ],
)
def test_answers_outside_the_schema_are_rejected(rich_grant: Grant, bad: dict[str, Any]) -> None:
    with pytest.raises(RejectEvent):
        process(submitted(rich_grant.public_id, answers={**RICH_ANSWERS, **bad}), "core-to-o1")
    assert not Application.objects.exists()


def test_required_yes_no_accepts_a_negative_answer(rich_grant: Grant) -> None:
    process(submitted(rich_grant.public_id, answers={**RICH_ANSWERS, "agree": False}), "core-to-o1")
    assert Application.objects.get().answers["agree"] is False
