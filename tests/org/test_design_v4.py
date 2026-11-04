"""The 23 Oct 2026 design update on the org sites: Compare applicants,
Published grants, the application's Activity tab and the reviewer's private notes."""

from datetime import timedelta
from typing import Any

from django.test import Client
from django.utils import timezone

from it42.common.models import OutboxEvent
from it42.org.applications.models import ReviewNote
from it42.org.review.models import Assessment, PanelMember, PanelTask, ReviewerNote


def _assess(seat: PanelMember, application: Any, grade: int, text: str = "SECRET-TEXT") -> None:
    Assessment.objects.create(
        member=seat,
        application=application,
        assessment=text,
        preliminary_statement=text,
        preliminary_grade=grade,
    )


def test_compare_applicants_hides_scores_until_the_review_is_done(
    admin_client: Client,
    make_grant: Any,
    make_application: Any,
    make_panel: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    a, b = make_seat(panel, "a@example.org"), make_seat(panel, "b@example.org")
    assign(a, app), assign(b, app)
    task = make_task(panel, PanelTask.Kind.ASSESSMENT)
    _assess(a, app, 7)
    url = f"/grants/{grant.pk}/applications/"
    page = admin_client.get(url).content.decode()
    assert "Compare applicants" in page and "1 / 2 reviews in" in page
    assert "avg of" not in page
    _assess(b, app, 8)
    task.ends_at = timezone.now() - timedelta(minutes=1)  # the review is done: grades are shared
    task.starts_at = task.ends_at - timedelta(days=1)
    task.save()
    page = admin_client.get(url).content.decode()
    assert "7.5" in page and "avg of 2 / 2 reviews" in page


def test_compare_applicants_filters_by_status(
    admin_client: Client, make_grant: Any, make_application: Any
) -> None:
    grant = make_grant()
    make_application(grant, name="Kept Received")
    other = make_application(grant, name="Moved Along")
    other.status = "under_review"
    other.save()
    page = admin_client.get(f"/grants/{grant.pk}/applications/?status=under_review").content
    assert b"Moved Along" in page and b"Kept Received" not in page
    assert b"Under review <span" in page
    # unknown statuses show everything
    page = admin_client.get(f"/grants/{grant.pk}/applications/?status=bogus").content
    assert b"Moved Along" in page and b"Kept Received" in page


def test_published_grants_page(
    admin_client: Client,
    make_grant: Any,
    make_application: Any,
    make_panel: Any,
    make_seat: Any,
    assign: Any,
) -> None:
    grant = make_grant("Open call")
    make_grant("Still a draft", status="draft")
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    seat = make_seat(panel, "a@example.org")
    assign(seat, app)
    _assess(seat, app, 6)
    page = admin_client.get("/grants/published/").content.decode()
    assert "Open call" in page and "Still a draft" not in page
    assert "Panel A" in page and "100%" in page
    assert "+1 today" in page
    assert "SECRET-TEXT" not in page
    board = admin_client.get("/").content.decode()
    assert "/grants/published/" in board and "1 reviewer" in board


def test_activity_tab_lists_notes_and_hides_grades_until_shared(
    admin_client: Client,
    make_grant: Any,
    make_application: Any,
    make_panel: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    seat = make_seat(panel, "a@example.org")
    assign(seat, app)
    task = make_task(panel, PanelTask.Kind.ASSESSMENT)
    _assess(seat, app, 9)
    admin_client.post(f"/applications/{app.pk}/notes/", {"text": "NOTE-MARKER"})
    page = admin_client.get(f"/applications/{app.pk}/").content.decode()
    assert "NOTE-MARKER" in page and "sent an assessment" in page
    assert "Grade 9/10" not in page and "SECRET-TEXT" not in page
    assert "1 of 1 in" in page
    task.ends_at = timezone.now() - timedelta(minutes=1)
    task.starts_at = task.ends_at - timedelta(days=1)
    task.save()
    page = admin_client.get(f"/applications/{app.pk}/").content.decode()
    assert "Grade 9/10" in page and "SECRET-TEXT" in page
    assert ReviewNote.objects.count() == 1 and not OutboxEvent.objects.exists()


def test_reviewer_notes_are_private_to_their_author(
    admin_client: Client,
    make_grant: Any,
    make_application: Any,
    make_panel: Any,
    make_seat: Any,
    assign: Any,
    seat_client: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    mine = make_seat(panel, "rev@example.org")
    chair = make_seat(panel, "chair@example.org", PanelMember.Role.CHAIR)
    assign(mine, app)
    url = f"/panels/{panel.pk}/applications/{app.pk}/"
    me = seat_client(mine)
    assert me.post(url + "notes/", {"text": "MY-NOTE"}).status_code == 302
    note = ReviewerNote.objects.get()
    assert b"MY-NOTE" in me.get(url).content
    other = seat_client(chair)
    assert b"MY-NOTE" not in other.get(url).content
    assert other.post(url + f"notes/{note.pk}/delete/").status_code == 404
    assert not OutboxEvent.objects.exists()
    # unassigned reviewers cannot write notes on applications they cannot open
    stranger = make_seat(panel, "x@example.org")
    assert seat_client(stranger).post(url + "notes/", {"text": "NO"}).status_code == 404
    assert me.post(url + f"notes/{note.pk}/delete/").status_code == 302
    assert not ReviewerNote.objects.exists()


def test_fo_never_sees_reviewer_notes(
    admin_client: Client,
    make_grant: Any,
    make_application: Any,
    make_panel: Any,
    make_seat: Any,
    assign: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    seat = make_seat(panel, "rev@example.org")
    assign(seat, app)
    ReviewerNote.objects.create(member=seat, application=app, text="PRIVATE-NOTE")
    assert b"PRIVATE-NOTE" not in admin_client.get(f"/applications/{app.pk}/").content
    assert (
        b"PRIVATE-NOTE"
        not in admin_client.get(f"/review/{panel.pk}/applications/{app.pk}/").content
    )
