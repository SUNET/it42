import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.models import OutboxEvent
from it42.core.accounts.models import User
from it42.core.applications.models import ApplicationCopy, QuestionCopy, StatusChange
from it42.core.catalog.models import PublicGrant
from tests.board_browser import board_browser, check_unsaved_card_text


@pytest.fixture
def g1_app(a2: User, make_grant: Callable[..., PublicGrant]) -> ApplicationCopy:
    return ApplicationCopy.objects.create(
        public_id=uuid.uuid4(),
        user=a2,
        org_slug="o1",
        grant=make_grant("o1"),
        status="received",
        submitted_at=timezone.now(),
        last_seq=1,
    )


@pytest.fixture
def g2_app(a2: User, make_grant: Callable[..., PublicGrant]) -> ApplicationCopy:
    return ApplicationCopy.objects.create(
        public_id=uuid.uuid4(),
        user=a2,
        org_slug="o2",
        grant=make_grant("o2"),
        status="received",
        submitted_at=timezone.now(),
        last_seq=1,
    )


def status_changed(app: ApplicationCopy, status: str, seq: int) -> bytes:
    return Envelope(
        type="application.status_changed",
        payload={"application_id": str(app.public_id), "status": status, "seq": seq},
        application_id=app.public_id,
        seq=seq,
    ).to_json()


def question_asked(app: ApplicationCopy, seq: int, **payload: Any) -> bytes:
    body = {
        "application_id": str(app.public_id),
        "question_id": str(uuid.uuid4()),
        "text": "Budget breakdown?",
        "seq": seq,
    }
    body.update(payload)
    return Envelope(
        type="question.asked", payload=body, application_id=app.public_id, seq=seq
    ).to_json()


def test_status_change_is_applied(g1_app: ApplicationCopy) -> None:
    process(status_changed(g1_app, "under_review", 2), "o1-to-core")
    g1_app.refresh_from_db()
    assert (g1_app.status, g1_app.last_seq) == ("under_review", 2)
    assert StatusChange.objects.get().status == "under_review"


def test_forged_status_change_for_another_orgs_application(
    g1_app: ApplicationCopy, g2_app: ApplicationCopy
) -> None:
    """o1 names a2's g2 application (belongs to o2): rejected, nothing changes."""
    with pytest.raises(RejectEvent):
        process(status_changed(g2_app, "rejected", 99), "o1-to-core")
    g2_app.refresh_from_db()
    assert (g2_app.status, g2_app.last_seq) == ("received", 1)
    assert not StatusChange.objects.exists()


def test_stale_and_repeated_seq_are_ignored(g1_app: ApplicationCopy) -> None:
    process(status_changed(g1_app, "approved", 3), "o1-to-core")
    process(status_changed(g1_app, "under_review", 2), "o1-to-core")  # older
    process(status_changed(g1_app, "rejected", 3), "o1-to-core")  # same seq, new event id
    g1_app.refresh_from_db()
    assert (g1_app.status, g1_app.last_seq) == ("approved", 3)


@pytest.mark.parametrize("status", ["submitted", "received", "bogus"])
def test_org_cannot_set_core_only_statuses(g1_app: ApplicationCopy, status: str) -> None:
    with pytest.raises(RejectEvent):
        process(status_changed(g1_app, status, 2), "o1-to-core")


def test_redelivery_with_same_event_id_changes_nothing(g1_app: ApplicationCopy) -> None:
    raw = status_changed(g1_app, "under_review", 2)
    assert process(raw, "o1-to-core") is True
    g1_app.status = "needs_info"
    g1_app.save()
    assert process(raw, "o1-to-core") is False
    g1_app.refresh_from_db()
    assert g1_app.status == "needs_info"
    assert StatusChange.objects.count() == 1


def test_question_is_stored_and_answer_goes_back(
    g1_app: ApplicationCopy, u2_client: Client
) -> None:
    process(question_asked(g1_app, 2), "o1-to-core")
    question = QuestionCopy.objects.get()
    page = u2_client.get(f"/my/applications/{g1_app.public_id}/").content.decode()
    assert "Budget breakdown?" in page
    u2_client.post(f"/my/questions/{question.pk}/answer/", {"answer": "40% hardware"})
    question.refresh_from_db()
    assert question.answer == "40% hardware"
    event = OutboxEvent.objects.get()
    assert (event.exchange, event.type) == ("core-to-o1", "question.answered")
    assert event.payload["question_id"] == str(question.question_public_id)
    # A second answer is refused.
    u2_client.post(f"/my/questions/{question.pk}/answer/", {"answer": "changed"})
    question.refresh_from_db()
    assert question.answer == "40% hardware"
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_reply_card_protects_unsaved_text(g1_app: ApplicationCopy, u2_client: Client) -> None:
    process(question_asked(g1_app, 2), "o1-to-core")
    with board_browser(u2_client) as page:
        page.goto("/my/applications/")
        page.locator("a[data-board-card]").click()
        frame = page.get_by_role("dialog").frame_locator("iframe")
        frame.get_by_role("tab", name="Messages").click()
        reply = frame.get_by_role("textbox", name="Your answer")
        check_unsaved_card_text(page, reply, lambda: reply.press("Escape"))
    assert QuestionCopy.objects.get().answered_at is None


@pytest.mark.django_db(transaction=True)
def test_reply_card_guards_call_link_but_allows_sending_reply(g1_app, u2_client) -> None:
    process(question_asked(g1_app, 2), "o1-to-core")
    with board_browser(u2_client) as page:
        page.goto("/my/applications/")
        page.locator("a[data-board-card]").click()
        frame = page.get_by_role("dialog").frame_locator("iframe")
        messages = frame.get_by_role("tab", name="Messages")
        messages.click()
        reply = frame.get_by_role("textbox", name="Your answer")
        reply.fill("Revised budget")
        frame.get_by_role("tab", name="Grant details").click()
        with page.expect_event("dialog", timeout=5000) as warning:
            page.once("dialog", lambda prompt: prompt.dismiss())
            frame.get_by_role("link", name="Open the call page").click()
        assert warning.value.type == "beforeunload"
        messages.click()
        assert reply.input_value() == "Revised budget"
        frame.get_by_role("button", name="Send answer").click()
        page.wait_for_url(f"**/my/applications/{g1_app.public_id}/")
    assert QuestionCopy.objects.get().answer == "Revised budget"


def test_other_users_cannot_answer(g1_app: ApplicationCopy, make_user: Callable[..., User]) -> None:
    process(question_asked(g1_app, 2), "o1-to-core")
    question = QuestionCopy.objects.get()
    other = Client()
    other.force_login(make_user("a1"))
    assert other.post(f"/my/questions/{question.pk}/answer/", {"answer": "x"}).status_code == 404


def test_question_for_another_orgs_application_is_rejected(g2_app: ApplicationCopy) -> None:
    with pytest.raises(RejectEvent):
        process(question_asked(g2_app, 2), "o1-to-core")
    assert not QuestionCopy.objects.exists()


@pytest.mark.parametrize("payload", [{"text": ""}, {"question_id": "nope"}])
def test_invalid_questions_are_rejected(g1_app: ApplicationCopy, payload: dict[str, Any]) -> None:
    with pytest.raises(RejectEvent):
        process(question_asked(g1_app, 2, **payload), "o1-to-core")
