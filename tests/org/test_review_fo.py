"""Review panel management on the staff site."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.test import Client
from django.utils import timezone

from it42.common.pdf import check_pdf_bytes
from it42.org.applications.models import ReviewNote
from it42.org.review.models import (
    Assessment,
    Assignment,
    Declaration,
    FinalStatement,
    Meeting,
    Panel,
    PanelMember,
    PanelTask,
    ReviewerProfile,
)

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _body(response: Any) -> bytes:
    return b"".join(response.streaming_content)


def _stamp(dt: Any) -> str:
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


def test_admin_creates_and_edits_a_panel(admin_client: Client) -> None:
    response = admin_client.post("/review/new/", {"name": "Panel A", "description": "Energy"})
    panel = Panel.objects.get()
    assert response.status_code == 302 and response["Location"] == f"/review/{panel.pk}/"
    assert admin_client.post(f"/review/{panel.pk}/edit/", {"name": "Panel B"}).status_code == 302
    panel.refresh_from_db()
    assert panel.name == "Panel B" and panel.description == ""
    assert admin_client.post(f"/review/{panel.pk}/delete/").status_code == 302
    assert not Panel.objects.exists()


def test_member_can_view_but_not_manage(
    member_client: Client, make_panel: Callable[..., Any], make_grant: Any
) -> None:
    panel = make_panel("Panel A", make_grant())
    assert member_client.get("/review/").status_code == 200
    page = member_client.get(f"/review/{panel.pk}/")
    assert page.status_code == 200
    assert b"Add seat" not in page.content and b"Delete panel" not in page.content
    assert member_client.get("/review/new/").status_code == 403
    assert (
        member_client.post(f"/review/{panel.pk}/seats/add/", {"email": "x@y.z"}).status_code == 403
    )
    assert member_client.get(f"/review/{panel.pk}/tasks/new/").status_code == 403
    assert member_client.post(f"/review/{panel.pk}/delete/").status_code == 403
    assert Panel.objects.filter(pk=panel.pk).exists()


def test_seats_are_added_by_email_with_a_role(
    admin_client: Client, make_panel: Callable[..., Any], make_user: Callable[..., Any]
) -> None:
    panel = make_panel()
    make_user("r2", email="peter.lund@chalmers.se")  # logged in before being seated
    url = f"/review/{panel.pk}/seats/add/"
    admin_client.post(url, {"email": "Ingrid.Nystrom@umu.se", "role": "chairperson"})
    admin_client.post(url, {"email": "peter.lund@chalmers.se", "role": "reviewer"})
    seats = {s.email: s for s in PanelMember.objects.filter(panel=panel)}
    assert seats["ingrid.nystrom@umu.se"].role == "chairperson"
    assert seats["ingrid.nystrom@umu.se"].user_id is None
    assert seats["peter.lund@chalmers.se"].user is not None
    # a duplicate is refused with a message, not a crash
    response = admin_client.post(
        url, {"email": "ingrid.nystrom@umu.se", "role": "reviewer"}, follow=True
    )
    assert b"already has a seat" in response.content
    assert PanelMember.objects.filter(panel=panel).count() == 2
    seat = seats["ingrid.nystrom@umu.se"]
    admin_client.post(f"/review/{panel.pk}/seats/{seat.pk}/role/", {"role": "supporting_admin"})
    seat.refresh_from_db()
    assert seat.role == "supporting_admin"
    admin_client.post(f"/review/{panel.pk}/seats/{seat.pk}/remove/")
    assert not PanelMember.objects.filter(pk=seat.pk).exists()


def test_grants_are_attached_and_detached(
    admin_client: Client, make_panel: Callable[..., Any], make_grant: Any
) -> None:
    panel = make_panel()
    draft = make_grant("draft", status="draft")
    g1 = make_grant("g1")
    admin_client.post(f"/review/{panel.pk}/grants/link/", {"grant_id": draft.pk})
    assert not panel.grants.exists()
    admin_client.post(f"/review/{panel.pk}/grants/link/", {"grant_id": g1.pk})
    assert list(panel.grants.all()) == [g1]
    admin_client.post(f"/review/{panel.pk}/grants/{g1.pk}/unlink/")
    assert not panel.grants.exists()


def test_tasks_and_meetings(admin_client: Client, make_panel: Callable[..., Any]) -> None:
    panel = make_panel()
    now = timezone.now()
    body = {
        "kind": "assessment",
        "title": "Write assessments",
        "starts_at": _stamp(now - timedelta(hours=1)),
        "ends_at": _stamp(now + timedelta(days=3)),
    }
    assert admin_client.post(f"/review/{panel.pk}/tasks/new/", body).status_code == 302
    task = PanelTask.objects.get()
    assert task.kind == "assessment" and task.is_open(now)
    # a second task of a special kind is refused by the form
    response = admin_client.post(f"/review/{panel.pk}/tasks/new/", body)
    assert response.status_code == 200 and b"already has a task of this kind" in response.content
    # end before start is refused
    response = admin_client.post(
        f"/review/{panel.pk}/tasks/new/", {**body, "kind": "other", "ends_at": body["starts_at"]}
    )
    assert response.status_code == 200 and b"after the start" in response.content
    # the FO may move the deadline into the past (re-closing the task)
    past = {**body, "ends_at": _stamp(now - timedelta(minutes=5))}
    assert admin_client.post(f"/review/{panel.pk}/tasks/{task.pk}/edit/", past).status_code == 302
    task.refresh_from_db()
    assert task.has_ended(now)
    edit_page = admin_client.get(f"/review/{panel.pk}/tasks/{task.pk}/edit/")
    assert past["ends_at"].encode() in edit_page.content  # datetime-local round trip
    admin_client.post(f"/review/{panel.pk}/tasks/{task.pk}/delete/")
    assert not PanelTask.objects.exists()

    meeting = {
        "title": "Panel meeting",
        "starts_at": _stamp(now + timedelta(days=7)),
        "ends_at": "",
        "location": "Room 2",
        "notes": "",
    }
    assert admin_client.post(f"/review/{panel.pk}/meetings/new/", meeting).status_code == 302
    m = Meeting.objects.get()
    assert m.location == "Room 2" and m.ends_at is None
    page = admin_client.get(f"/review/{panel.pk}/")
    assert b"Panel meeting" in page.content and b"Room 2" in page.content
    admin_client.post(f"/review/{panel.pk}/meetings/{m.pk}/delete/")
    assert not Meeting.objects.exists()


def test_assignment_form_uses_one_checkbox_per_seat(
    admin_client: Client,
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("A", grant)
    app = make_application(grant)
    foreign = make_application(make_grant("g2"))
    r1 = make_seat(panel, "r1@example.org")
    r2 = make_seat(panel, "r2@example.org")
    url = f"/review/{panel.pk}/applications/{app.pk}/assign/"
    admin_client.post(url, {f"seat_{r1.pk}": "on", f"seat_{r2.pk}": "on"})
    assert Assignment.objects.filter(application=app).count() == 2
    admin_client.post(url, {f"seat_{r2.pk}": "on", "seat_x": "on"})
    assert [a.member_id for a in Assignment.objects.filter(application=app)] == [r2.pk]
    assert (
        admin_client.post(f"/review/{panel.pk}/applications/{foreign.pk}/assign/").status_code
        == 404
    )
    page = admin_client.get(f"/review/{panel.pk}/applications/{app.pk}/")
    assert f'name="seat_{r2.pk}" checked'.encode() in page.content
    assert f'name="seat_{r1.pk}" checked'.encode() not in page.content


def test_panel_application_page_hides_assessments_until_the_deadline(
    admin_client: Client,
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
    make_task: Any,
    assign: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    seat = make_seat(panel, "r1@example.org")
    assign(seat, app)
    task = make_task(panel, PanelTask.Kind.ASSESSMENT)
    Assessment.objects.create(
        member=seat,
        application=app,
        assessment="SECRET-TEXT",
        preliminary_statement="s",
        preliminary_grade=7,
    )
    Declaration.objects.create(
        member=seat,
        application=app,
        in_conflict=True,
        conflict_reason="Co-author",
        competence="high",
    )
    url = f"/review/{panel.pk}/applications/{app.pk}/"
    page = admin_client.get(url)
    assert b"SECRET-TEXT" not in page.content and b"Private to each reviewer until" in page.content
    assert b"Co-author" in page.content  # declarations are always visible to the FO
    task.ends_at = timezone.now() - timedelta(minutes=1)
    task.save()
    page = admin_client.get(url)
    assert b"SECRET-TEXT" in page.content
    # the staff application page summarises the panel too
    detail = admin_client.get(f"/applications/{app.pk}/")
    assert b"Panel A" in detail.content and b"7/10" in detail.content


def test_final_statement_is_shown_to_the_fo(
    admin_client: Client,
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
    make_task: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("A", grant)
    app = make_application(grant)
    chair = make_seat(panel, "chair@example.org", PanelMember.Role.CHAIR)
    url = f"/review/{panel.pk}/applications/{app.pk}/"
    make_task(panel, PanelTask.Kind.ASSESSMENT)
    final_task = make_task(panel, PanelTask.Kind.FINAL, open_=False)
    assert b"Final statement" not in admin_client.get(url).content  # review still running
    FinalStatement.objects.create(
        panel=panel,
        application=app,
        author=chair,
        final_statement="Fund it",
        final_grade=9,
        novelty="n",
        novelty_grade=8,
        merits="m",
        merits_grade=7,
        feasibility="f",
        feasibility_grade=6,
        quality="q",
        quality_grade=5,
    )
    assert b"Fund it" not in admin_client.get(url).content
    panel.review_closed_at = timezone.now()
    panel.save()
    final_task.starts_at = timezone.now() - timedelta(minutes=1)
    final_task.save()
    page = admin_client.get(url)
    assert b"Fund it" in page.content and b"9/10" in page.content and b"5/10" in page.content


def test_seat_page_shows_payment_info_and_passport_to_admins_only(
    admin_client: Client,
    member_client: Client,
    make_panel: Callable[..., Any],
    make_seat: Any,
    tmp_path: Any,
) -> None:
    panel = make_panel()
    seat = make_seat(panel, "r1@example.org")
    profile = ReviewerProfile.objects.create(
        user=seat.user,
        address="Storgatan 1",
        account_holder="Ingrid",
        bank_name="SEB",
        iban="SE1234567890",
        bic="ESSESESS",
        keywords="photonics, lasers",
        passport_name="pass.pdf",
        passport_sha256=check_pdf_bytes(PDF),
        passport_size=len(PDF),
        passport_uploaded_at=timezone.now(),
    )
    from django.core.files.base import ContentFile

    profile.passport.save("pass.pdf", ContentFile(PDF), save=True)
    url = f"/review/{panel.pk}/seats/{seat.pk}/"
    page = admin_client.get(url)
    assert b"SE1234567890" in page.content and b"photonics" in page.content
    download = admin_client.get(url + "passport/")
    assert download.status_code == 200
    assert _body(download).startswith(b"%PDF")
    assert member_client.get(url).status_code == 403
    assert member_client.get(url + "passport/").status_code == 403
    # the panel page links to the seat page for admins only
    assert url.encode() in admin_client.get(f"/review/{panel.pk}/").content
    assert url.encode() not in member_client.get(f"/review/{panel.pk}/").content


def test_reviewers_are_not_listed_as_pending_members(
    admin_client: Client,
    make_panel: Callable[..., Any],
    make_seat: Any,
    make_user: Callable[..., Any],
) -> None:
    make_seat(make_panel(), "r1@example.org")  # bound user r1 without a membership
    make_user("a1", email="a1@example.org")  # ordinary pending user
    page = admin_client.get("/members/")
    assert b"a1@example.org" in page.content and b"r1@example.org" not in page.content


def test_review_notes_stay_off_panel_pages(
    admin_client: Client,
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_member: Callable[..., Any],
) -> None:
    grant = make_grant()
    panel = make_panel("A", grant)
    app = make_application(grant)
    ReviewNote.objects.create(application=app, author=make_member("staff2"), text="NOTE-MARKER")
    assert (
        b"NOTE-MARKER" not in admin_client.get(f"/review/{panel.pk}/applications/{app.pk}/").content
    )


def test_admin_ends_the_review_early_and_can_undo_it(
    admin_client: Client,
    member_client: Client,
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
    make_task: Any,
) -> None:
    grant = make_grant()
    panel = make_panel("A", grant)
    make_task(panel, PanelTask.Kind.ASSESSMENT)
    final = make_task(panel, PanelTask.Kind.FINAL, open_=False)
    close, reopen = f"/review/{panel.pk}/review/close/", f"/review/{panel.pk}/review/reopen/"
    page = admin_client.get(f"/review/{panel.pk}/").content
    assert b"review in progress" in page and close.encode() in page
    assert member_client.post(close).status_code == 403
    assert admin_client.get(close).status_code == 405
    assert admin_client.post(close).status_code == 302
    panel.refresh_from_db()
    assert panel.review_closed_at is not None and panel.review_done(timezone.now())
    final.refresh_from_db()
    assert final.is_open(timezone.now())  # moved on to the next phase
    page = admin_client.get(f"/review/{panel.pk}/").content
    assert b"Ended early" in page and reopen.encode() in page
    assert admin_client.post(reopen).status_code == 302
    panel.refresh_from_db()
    assert panel.review_closed_at is None and not panel.review_done(timezone.now())
    # once a final statement exists the early end sticks
    admin_client.post(close)
    FinalStatement.objects.create(
        panel=panel,
        application=make_application(grant),
        author=make_seat(panel, "chair@example.org", PanelMember.Role.CHAIR),
        final_statement="Fund it",
        final_grade=9,
        novelty="n",
        novelty_grade=8,
        merits="m",
        merits_grade=7,
        feasibility="f",
        feasibility_grade=6,
        quality="q",
        quality_grade=5,
    )
    admin_client.post(reopen)
    panel.refresh_from_db()
    assert panel.review_closed_at is not None
