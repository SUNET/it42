"""Regression coverage for the granter queues, personal notes and board-only actions."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from it42.common.models import OutboxEvent
from it42.org.applications.models import Question
from it42.org.grants.models import BoardNote, Category
from it42.org.review.models import Assessment, Meeting, PanelTask
from tests.board_browser import board_browser


def cards(response):
    """Return the distinct visible cards, even when a panel appears under two calls."""
    return {c.key: c for group in response.context["sections"] for c in group["cards"]}


def test_queues_and_panel_progress(
    admin_client, make_grant, make_panel, make_seat, make_task, make_application, assign
):
    """The same queries power counts, panel milestones, search and both presentations."""
    draft = make_grant("Rural Health 2027", status="draft")
    call = make_grant("Clean Water Challenge")
    panel = make_panel("Panel A · Adaptation", call)
    reviewer = make_seat(panel, "river@example.org")
    app = make_application(call, name="Maya Okafor")
    app.answers["project_title"] = "Seagrass restoration"
    app.save()
    assign(reviewer, app)
    waiting = make_application(call, name="Sam Rivera")
    waiting.status = "awaiting_signature"
    waiting.save()
    make_task(panel, PanelTask.Kind.ASSESSMENT, title="Reviews due")
    meeting = Meeting.objects.create(
        panel=panel, title="Panel meeting", starts_at=timezone.now() + timedelta(hours=1)
    )
    tag = Category.objects.create(name="Hydrology")
    call.category = tag
    call.save()
    other = make_grant("Ocean Futures")
    panel.grants.add(other)
    decided = make_application(other, name="Jordan Lee")
    admin_client.post(reverse("application_status", args=[decided.pk]), {"status": "approved"})
    rejected = make_application(other)
    admin_client.post(reverse("application_status", args=[rejected.pk]), {"status": "rejected"})

    all_cards = cards(admin_client.get("/"))
    assert len(all_cards) == 5
    assert all_cards[f"grant:{draft.pk}"].stage == "draft"
    panel_card = all_cards[f"panel:{panel.pk}"]
    assert panel_card.progress == (0, 1)
    assert panel_card.when == timezone.localdate(meeting.starts_at)
    assert panel_card.date_label == "Panel meeting"
    attention = cards(admin_client.get("/", {"tab": "attention"}))
    assert set(attention) == {f"panel:{panel.pk}", f"application:{waiting.pk}"}
    for view in ["table", "board"]:
        response = admin_client.get("/", {"view": view, "tab": "granted"})
        assert set(cards(response)) == {f"application:{decided.pk}"}
        assert cards(response)[f"application:{decided.pk}"].when == timezone.localdate()
        assert set(cards(admin_client.get("/", {"q": str(app.public_id), "view": view}))) == {
            f"application:{app.pk}"
        }
    assert (
        cards(admin_client.get("/", {"q": "mAyA", "tag": tag.pk}))[f"application:{app.pk}"].title
        == "Seagrass restoration"
    )
    assert not cards(admin_client.get("/", {"q": "Jordan", "tag": tag.pk}))
    assert (
        len(admin_client.get("/", {"group": "call", "status": "In review"}).context["sections"])
        == 2
    )
    assert (
        admin_client.get("/", {"group": "workflow", "tab": "waiting"}).context["sections"][0][
            "name"
        ]
        == "Organisation sign-off"
    )

    Assessment.objects.create(
        member=reviewer,
        application=app,
        assessment="CONFIDENTIAL",
        preliminary_statement="PRIVATE",
        preliminary_grade=8,
    )
    page = admin_client.get("/")
    assert cards(page)[f"panel:{panel.pk}"].progress == (1, 1)
    assert cards(page)[f"application:{app.pk}"].badge == "Reviews received"
    assert b"CONFIDENTIAL" not in page.content
    panel.review_closed_at = timezone.now()
    panel.save()
    # A closed assessment period still needs attention while its meeting is upcoming.
    assert f"panel:{panel.pk}" in cards(admin_client.get("/", {"tab": "attention"}))
    meeting.delete()
    assert f"panel:{panel.pk}" not in cards(admin_client.get("/", {"tab": "attention"}))


def test_open_and_answered_questions_route_to_correspondence(
    member_client, make_application, make_user
):
    """Open questions wait on applicants, while an answer returns work to staff."""
    app = make_application()
    q = Question.objects.create(
        application=app, asked_by=make_user("author"), text="Confirm dates?"
    )
    key = f"application:{app.pk}"
    assert cards(member_client.get("/", {"tab": "waiting"}))[key].badge == "Waiting for applicant"
    q.answer = "Confirmed."
    q.answered_at = timezone.now()
    q.save()
    card = cards(member_client.get("/", {"tab": "todo"}))[key]
    assert card.badge == "Review applicant response" and card.url.endswith("#questions")


def test_selection_permissions_private_notes_and_pausing(
    admin_client, member_client, make_grant, make_application, client, make_user
):
    """Local changes preserve the public lifecycle and a note belongs only to its author."""
    grant = make_grant("Digital health")
    app = make_application(grant)
    grant_key, app_key = f"grant:{grant.pk}", f"application:{app.pk}"
    action = reverse("board_action")
    assert member_client.get(action).status_code == 405
    assert client.post(action, {"action": "note", "card": app_key}).status_code == 302
    client.force_login(make_user("outsider"))
    assert client.post(action, {"action": "note", "card": app_key}).status_code == 403
    for verb in ["pause", "resume", "tag"]:
        assert member_client.post(action, {"action": verb, "card": grant_key}).status_code == 403
    response = member_client.post(
        action + "?view=table",
        {"action": "note", "note": "My reminder", "card": [grant_key, app_key, grant_key]},
    )
    assert response.url == "/?view=table"
    assert BoardNote.objects.count() == 2
    assert len(cards(member_client.get("/", {"notes": "mine"}))) == 2
    assert not cards(admin_client.get("/", {"notes": "mine"}))
    assert b"My reminder" not in admin_client.get("/").content
    member_client.post(action, {"action": "note", "card": app_key, "note": ""})
    assert BoardNote.objects.count() == 1
    tag = Category.objects.create(name="Health")
    admin_client.post(action, {"action": "tag", "tag": tag.pk, "card": grant_key})
    assert grant_key in cards(admin_client.get("/", {"tag": tag.pk}))
    admin_client.post(action, {"action": "pause", "card": grant_key})
    grant.refresh_from_db()
    assert grant.board_paused and grant.status == "published"
    default = admin_client.get("/")
    assert grant_key not in cards(default)
    assert len(default.context["sections"][0]["columns"]) == 6
    assert set(cards(admin_client.get("/", {"tab": "paused"}))) == {grant_key}
    assert app_key in cards(admin_client.get("/", {"tab": "attention"}))
    admin_client.post(action, {"action": "resume", "card": grant_key})
    assert not cards(admin_client.get("/", {"tab": "paused"}))
    assert not OutboxEvent.objects.exists()


def test_archive_selection_is_atomic_and_retryable(member_client, make_application):
    """A stale selection cannot archive a pending application or partially move a batch."""
    accepted = make_application()
    active = make_application(accepted.grant)
    member_client.post(reverse("application_status", args=[accepted.pk]), {"status": "approved"})
    accepted.refresh_from_db()
    scheduled = accepted.archive_at
    action = reverse("board_action")
    key = f"application:{accepted.pk}"
    member_client.post(action, {"action": "archive", "card": [key, f"application:{active.pk}"]})
    accepted.refresh_from_db()
    assert accepted.archive_at == scheduled
    for bad in ["other:1", "application:no", "application:99999"]:
        member_client.post(action, {"action": "archive", "card": [key, bad]})
        assert key in cards(member_client.get("/"))
    member_client.post(action, {"action": "archive", "card": key})
    accepted.refresh_from_db()
    first = accepted.archive_at
    assert first < scheduled and accepted.status == "approved"
    assert key not in cards(member_client.get("/"))
    assert list(member_client.get(reverse("grant_archive")).context["applications"]) == [accepted]
    member_client.post(action, {"action": "archive", "card": key})
    accepted.refresh_from_db()
    assert accepted.archive_at == first
    assert OutboxEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_call_board_controls_and_archive_drop(
    admin_client, make_application, make_grant, make_panel, make_seat, make_task, assign, tmp_path
):
    """Use the actual desktop board and mobile table, including keyboard and drag actions."""
    make_grant("Rural Health 2027", status="draft")
    grant = make_grant("Clean Water Challenge")
    make_grant("Digital Health Pilots")
    panel = make_panel("Panel A · Adaptation", grant)
    chair = make_seat(panel, "chair@example.org")
    reviewer = make_seat(panel, "reviewer@example.org")
    reviewing = make_application(grant, name="Alex Lind")
    assign(chair, reviewing)
    assign(reviewer, reviewing)
    Assessment.objects.create(
        member=chair,
        application=reviewing,
        assessment="Complete",
        preliminary_statement="Complete",
        preliminary_grade=7,
    )
    make_task(panel, PanelTask.Kind.ASSESSMENT, title="Reviews due")
    waiting = make_application(grant, name="Sam Rivera")
    waiting.status = "awaiting_signature"
    waiting.answers["project_title"] = "Wetland restoration"
    waiting.save()
    decided = make_application(grant, name="Maya Okafor")
    decided.answers["project_title"] = "Seagrass restoration"
    decided.save()
    admin_client.post(reverse("application_status", args=[decided.pk]), {"status": "approved"})
    with board_browser(admin_client) as page:
        page.set_viewport_size({"width": 1920, "height": 1024})
        page.goto("/")
        assert page.locator(".cb-board > section").count() == 6
        assert page.locator(".it-sidebar.is-collapsed, .it-panel.is-collapsed").count() == 2
        page.screenshot(path=tmp_path / "call-board-desktop.png")
        page.get_by_role("button", name="Stats", exact=True).click()
        assert page.get_by_role("heading", name="Board stats").is_visible()
        page.keyboard.press("Escape")
        page.get_by_role("link", name="Panel A · Adaptation", exact=True).click()
        frame = page.get_by_role("dialog").frame_locator("iframe")
        frame.get_by_role("heading", name="Panel A · Adaptation").wait_for()
        page.get_by_role("button", name="Close card").click()
        card = page.locator("[data-archive-card]")
        card.drag_to(page.locator("[data-archive-drop]"))
        page.get_by_text("Archived.", exact=True).wait_for()
        assert page.locator("[data-archive-card]").count() == 0

        page.set_viewport_size({"width": 390, "height": 844})
        header = page.locator("[data-call-board]")
        assert header.evaluate("(el) => el.scrollWidth <= el.clientWidth + 1")
        page.get_by_role("link", name="Table", exact=True).click()
        page.get_by_role("searchbox").fill("Wetland")
        page.get_by_role("searchbox").press("Enter")
        row = page.locator(".cb-table tbody tr")
        assert row.count() == 1 and "Wetland restoration" in row.inner_text()
        row.locator("summary").press("Enter")
        row.get_by_label("Note to self").fill("Check signature tomorrow")
        row.get_by_role("button", name="Save personal note").click()
        page.get_by_text("Personal note updated.").wait_for()
        page.screenshot(path=tmp_path / "call-board-mobile.png")


def test_panel_setup_keeps_the_originating_call(
    admin_client, member_client, make_grant, make_panel
):
    """The to-do card supports creating a panel or attaching an existing one to its call."""
    grant = make_grant("Arctic field studies")
    panel = make_panel("Polar panel")
    card = cards(admin_client.get("/"))[f"grant:{grant.pk}"]
    directory = reverse("call_panels", args=[grant.pk])
    assert card.url == directory
    assert b"Attach call to Polar panel" in admin_client.get(directory).content
    assert b"Attach call to Polar panel" not in member_client.get(directory).content
    new = reverse("call_panel_create", args=[grant.pk])
    assert member_client.post(new, {"name": "Denied", "description": ""}).status_code == 403
    admin_client.post(new, {"name": "New panel", "description": ""})
    assert cards(admin_client.get("/"))[f"grant:{grant.pk}"].url.endswith("#seats")
    admin_client.post(reverse("panel_grant_link", args=[panel.pk]), {"grant_id": grant.pk})
    assert list(panel.grants.all()) == [grant]
    draft = make_grant("Draft call", status="draft")
    assert admin_client.get(reverse("call_panel_create", args=[draft.pk])).status_code == 404
