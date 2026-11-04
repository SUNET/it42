import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.org.applications.models import Application, ApplicationDocument, Question, ReviewNote
from it42.org.grants.models import Grant


@pytest.fixture
def application(make_user: Callable[..., Any]) -> Application:
    grant = Grant.objects.create(
        title="g1",
        description="d",
        deadline=timezone.localdate() + timedelta(days=30),
        form_schema=[{"name": "budget", "label": "Budget", "type": "number", "required": True}],
        status=Grant.Status.PUBLISHED,
        created_by=make_user("creator"),
    )
    return Application.objects.create(
        public_id=uuid.uuid4(),
        grant=grant,
        applicant_subject="a2",
        applicant_name="Oskar Bergström",
        answers={"budget": "1500"},
        submitted_at=timezone.now(),
        seq=1,
    )


@pytest.fixture
def reviewer(make_member: Callable[..., Any]) -> Client:
    client = Client()
    client.force_login(make_member("a1"))
    return client


def test_reviewer_sees_application(reviewer: Client, application: Application) -> None:
    body = reviewer.get(f"/applications/{application.pk}/").content.decode()
    assert "Oskar Bergström" in body and "1500" in body


def test_non_member_cannot_see_application(
    client: Client, make_user: Callable[..., Any], application: Application
) -> None:
    client.force_login(make_user("a3"))
    response = client.get(f"/applications/{application.pk}/")
    assert response.status_code == 403
    assert b"Oskar" not in response.content


def test_status_change_emits_event_with_next_seq(
    reviewer: Client, application: Application
) -> None:
    reviewer.post(f"/applications/{application.pk}/status/", {"status": "under_review"})
    application.refresh_from_db()
    assert (application.status, application.seq) == ("under_review", 2)
    event = OutboxEvent.objects.get()
    assert (event.type, event.seq, event.payload["status"]) == (
        "application.status_changed",
        2,
        "under_review",
    )
    # Same status again: no new event.
    reviewer.post(f"/applications/{application.pk}/status/", {"status": "under_review"})
    assert OutboxEvent.objects.count() == 1


@pytest.mark.parametrize("status", ["submitted", "received", "bogus"])
def test_org_cannot_set_core_statuses(
    reviewer: Client, application: Application, status: str
) -> None:
    reviewer.post(f"/applications/{application.pk}/status/", {"status": status})
    application.refresh_from_db()
    assert application.status == "received"
    assert not OutboxEvent.objects.exists()


def test_question_emits_event(reviewer: Client, application: Application) -> None:
    reviewer.post(f"/applications/{application.pk}/questions/", {"text": "Budget breakdown?"})
    question = Question.objects.get()
    event = OutboxEvent.objects.get()
    assert event.type == "question.asked"
    assert event.payload == {
        "application_id": str(application.public_id),
        "question_id": str(question.public_id),
        "text": "Budget breakdown?",
        "seq": 2,
    }


def test_review_notes_never_produce_events(reviewer: Client, application: Application) -> None:
    reviewer.post(f"/applications/{application.pk}/notes/", {"text": "Strong team, weak budget"})
    assert ReviewNote.objects.get().text == "Strong team, weak budget"
    assert not OutboxEvent.objects.exists()


def test_document_download(reviewer: Client, application: Application) -> None:
    doc = ApplicationDocument(application=application, original_name="cv.pdf", sha256="x")
    doc.file.save("cv.pdf", ContentFile(b"%PDF-1.4"), save=True)
    response = reviewer.get(f"/applications/{application.pk}/documents/{doc.pk}/")
    assert response.status_code == 200
    assert response.getvalue() == b"%PDF-1.4"
    assert "attachment" in response["Content-Disposition"]


def answered(application: Application, question: Question, answer: str = "40% hardware") -> bytes:
    return Envelope(
        type="question.answered",
        payload={
            "application_id": str(application.public_id),
            "question_id": str(question.public_id),
            "answer": answer,
        },
        application_id=application.public_id,
    ).to_json()


def test_answer_arrives(application: Application, make_member: Callable[..., Any]) -> None:
    question = Question.objects.create(application=application, text="q", asked_by=make_member("s"))
    process(answered(application, question), "core-to-o1")
    question.refresh_from_db()
    assert question.answer == "40% hardware"
    assert question.answered_at is not None


def test_answer_for_another_application_is_rejected(
    application: Application, make_member: Callable[..., Any]
) -> None:
    question = Question.objects.create(application=application, text="q", asked_by=make_member("s"))
    other = Application(public_id=uuid.uuid4())
    with pytest.raises(RejectEvent):
        process(answered(other, question), "core-to-o1")
