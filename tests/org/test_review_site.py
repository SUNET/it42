"""The reviewer site: gate, visibility and writing rules."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.test import Client
from django.utils import timezone

from it42.org.applications.models import Application, ApplicationDocument, Question, ReviewNote
from it42.org.review.models import (
    Assessment,
    Declaration,
    FinalStatement,
    Meeting,
    PanelMember,
    PanelTask,
)

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

FINAL = {
    "final_statement": "Fund it",
    "final_grade": "9",
    "novelty": "n",
    "novelty_grade": "8",
    "merits": "m",
    "merits_grade": "7",
    "feasibility": "f",
    "feasibility_grade": "6",
    "quality": "q",
    "quality_grade": "5",
}


def test_anonymous_is_sent_to_login(review_site: None) -> None:
    response = Client().get("/")
    assert response.status_code == 302 and response["Location"].startswith("/saml2/login/")
    assert Client().get("/healthz").status_code == 200


def test_user_without_a_seat_sees_the_not_a_reviewer_page(
    review_site: None,
    make_user: Callable[..., Any],
    make_panel: Callable[..., Any],
    make_member: Any,
) -> None:
    make_panel("Secret panel name")
    client = Client()
    client.force_login(make_user("a4", email="mattias@vr.se"))
    page = client.get("/")
    assert page.status_code == 403
    assert b"not on any review panel of Org 1" in page.content
    assert b"Secret panel name" not in page.content
    # being org staff does not help on the reviewer site
    client.force_login(make_member("staff1"))
    assert client.get("/").status_code == 403


def test_nothing_but_reviewer_work_is_routed(
    review_site: None, make_panel: Any, make_seat: Any, seat_client: Any
) -> None:
    client = seat_client(make_seat(make_panel(), "r1@example.org"))
    for path in ("/admin/", "/grants/", "/members/", "/applications/1/", "/review/"):
        assert client.get(path).status_code == 404, path
    home = client.get("/")
    assert home.status_code == 200
    assert b"My panels" in home.content and b"My profile" in home.content
    assert (
        b"Grants" not in home.content
        and b"Members" not in home.content
        and b"Dashboard" not in home.content
    )


def test_login_binds_the_seat_by_email(
    review_site: None, make_panel: Any, make_seat: Any, make_user: Callable[..., Any]
) -> None:
    make_seat(make_panel("Panel A"), "Ingrid.Nystrom@umu.se", user=False)
    client = Client()
    client.force_login(make_user("r1", email="ingrid.nystrom@UMU.se"))  # fires user_logged_in
    page = client.get("/")
    assert page.status_code == 200 and b"Panel A" in page.content
    assert PanelMember.objects.get().user is not None


def test_panel_list_shows_only_own_panels(
    make_panel: Any, make_seat: Any, seat_client: Any, make_task: Any
) -> None:
    mine, other = make_panel("Mine"), make_panel("Other")
    make_seat(other, "someone@example.org")
    seat = make_seat(mine, "r1@example.org", PanelMember.Role.CHAIR)
    make_task(mine, PanelTask.Kind.ASSESSMENT, title="Write")
    Meeting.objects.create(
        panel=mine, title="Kick-off", starts_at=timezone.now() + timedelta(days=1)
    )
    client = seat_client(seat)
    page = client.get("/")
    assert b"Mine" in page.content and b"Other" not in page.content
    assert b"Chairperson" in page.content and b"Open now: Write" in page.content
    assert b"<strong>Kick-off</strong>" in page.content  # the next-meeting box
    assert client.get(f"/panels/{other.pk}/").status_code == 404


def _setup(
    make_grant: Any, make_panel: Any, make_application: Any, make_seat: Any, assign: Any
) -> dict[str, Any]:
    grant = make_grant()
    panel = make_panel("Panel A", grant)
    app = make_application(grant)
    unassigned_app = make_application(grant, name="Nobody Assigned")
    chair = make_seat(panel, "chair@example.org", PanelMember.Role.CHAIR)
    reviewer = make_seat(panel, "rev@example.org")
    external = make_seat(panel, "ext@example.org", PanelMember.Role.EXTERNAL)
    support = make_seat(panel, "sup@example.org", PanelMember.Role.SUPPORT)
    assign(chair, app), assign(reviewer, app), assign(external, app)
    return {
        "grant": grant,
        "panel": panel,
        "app": app,
        "unassigned_app": unassigned_app,
        "chair": chair,
        "reviewer": reviewer,
        "external": external,
        "support": support,
        "url": f"/panels/{panel.pk}/applications/{app.pk}/",
    }


def test_reviewer_sees_assigned_applications_only(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    panel_url = f"/panels/{s['panel'].pk}/"
    reviewer = seat_client(s["reviewer"])
    page = reviewer.get(panel_url)
    assert b"Oskar Bergstr" in page.content and b"Nobody Assigned" not in page.content
    assert reviewer.get(s["url"]).status_code == 200
    other_url = f"/panels/{s['panel'].pk}/applications/{s['unassigned_app'].pk}/"
    assert reviewer.get(other_url).status_code == 404
    for role in ("chair", "support"):
        page = seat_client(s[role]).get(panel_url)
        assert b"Nobody Assigned" in page.content, role
        assert seat_client(s[role]).get(other_url).status_code == 200
    # the application page shows the answers and the applicant, never status/questions/notes
    Question.objects.create(application=s["app"], text="QUESTION-MARKER", asked_by=s["chair"].user)
    ReviewNote.objects.create(application=s["app"], author=s["chair"].user, text="NOTE-MARKER")
    page = reviewer.get(s["url"])
    assert b"Measure energy use." in page.content and b"oskar.bergstrom@kth.se" in page.content
    for marker in (
        b"QUESTION-MARKER",
        b"NOTE-MARKER",
        b"Review notes",
        b"Ask a question",
        b"Update",
    ):
        assert marker not in page.content, marker


def test_documents_download_for_visible_applications_only(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    seat_client: Any,
) -> None:
    from django.core.files.base import ContentFile

    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    doc = ApplicationDocument(
        application=s["app"], original_name="cv.pdf", sha256="x", size=len(PDF)
    )
    doc.file.save("cv.pdf", ContentFile(PDF), save=True)
    other = ApplicationDocument(
        application=s["unassigned_app"], original_name="o.pdf", sha256="x", size=len(PDF)
    )
    other.file.save("o.pdf", ContentFile(PDF), save=True)
    reviewer = seat_client(s["reviewer"])
    page = reviewer.get(s["url"])
    assert b"cv.pdf" in page.content
    response = reviewer.get(s["url"] + f"documents/{doc.pk}/")
    assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF")
    assert reviewer.get(s["url"] + f"documents/{other.pk}/").status_code == 404
    unassigned_url = (
        f"/panels/{s['panel'].pk}/applications/{s['unassigned_app'].pk}/documents/{other.pk}/"
    )
    assert reviewer.get(unassigned_url).status_code == 404
    assert seat_client(s["chair"]).get(unassigned_url).status_code == 200


def test_declaration_requires_the_conflict_window(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    reviewer = seat_client(s["reviewer"])
    body = {"in_conflict": "on", "conflict_reason": "Co-author", "competence": "high"}
    url = s["url"] + "declaration/"
    assert reviewer.post(url, body).status_code == 403  # no task yet
    assert b"no conflict-of-interest task" in reviewer.get(s["url"]).content
    task = make_task(s["panel"], PanelTask.Kind.CONFLICT)
    page = reviewer.get(s["url"])
    assert b'action="' + url.encode() in page.content
    assert reviewer.post(url, body).status_code == 302
    d = Declaration.objects.get(member=s["reviewer"])
    assert d.in_conflict and d.conflict_reason == "Co-author" and d.competence == "high"
    # a conflict needs a reason; competence is required
    response = reviewer.post(url, {"in_conflict": "on", "competence": "low"}, follow=True)
    assert b"Describe the conflict" in response.content
    assert reviewer.post(url, {"competence": "medium"}).status_code == 302  # no conflict: fine
    d.refresh_from_db()
    assert not d.in_conflict and d.competence == "medium"
    # supporting admins never declare; unassigned applications cannot be declared on
    assert seat_client(s["support"]).post(url, body).status_code == 403
    chair = seat_client(s["chair"])
    other = f"/panels/{s['panel'].pk}/applications/{s['unassigned_app'].pk}/declaration/"
    assert chair.post(other, body).status_code == 403
    assert chair.post(url, body).status_code == 302  # the chair is assigned here
    # the window closes
    task.ends_at = timezone.now() - timedelta(minutes=1)
    task.save()
    assert reviewer.post(url, body).status_code == 403
    page = reviewer.get(s["url"])
    assert b"The task closed" in page.content and b"competence medium" in page.content
    # chair and support see every declaration, reviewers only their own
    assert b"Co-author" in chair.get(s["url"]).content
    assert b"Co-author" in seat_client(s["support"]).get(s["url"]).content
    assert b"Declarations of the panel" not in reviewer.get(s["url"]).content


def test_assessments_are_private_until_the_deadline_then_frozen_and_shared(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    reviewer, external, chair, support = (
        seat_client(s[r]) for r in ("reviewer", "external", "chair", "support")
    )
    url = s["url"] + "assessment/"

    def body(who: str) -> dict[str, str]:
        return {
            "assessment": f"ASSESS-{who}",
            "preliminary_statement": f"STATEMENT-{who}",
            "preliminary_grade": "7",
        }

    assert reviewer.post(url, body("r")).status_code == 403  # no task
    task = make_task(s["panel"], PanelTask.Kind.ASSESSMENT)
    assert reviewer.post(url, body("r")).status_code == 302
    assert reviewer.post(url, {**body("r2"), "preliminary_grade": "8"}).status_code == 302  # drafts
    assert Assessment.objects.get(member=s["reviewer"]).preliminary_grade == 8
    assert external.post(url, body("e")).status_code == 302
    assert support.post(url, body("s")).status_code == 403
    assert (
        reviewer.post(url, {**body("bad"), "preliminary_grade": "11"}, follow=True).status_code
        == 200
    )
    assert Assessment.objects.get(member=s["reviewer"]).assessment == "ASSESS-r2"
    # private: each sees only their own
    mine = reviewer.get(s["url"]).content
    assert b"ASSESS-r2" in mine and b"ASSESS-e" not in mine and b"Panel assessments" not in mine
    assert b"ASSESS-r2" not in chair.get(s["url"]).content
    assert b"ASSESS-r2" not in support.get(s["url"]).content
    # deadline passes: shared, read-only, for everyone on the panel
    task.ends_at = timezone.now() - timedelta(minutes=1)
    task.save()
    assert reviewer.post(url, body("late")).status_code == 403
    for client in (reviewer, external, chair, support):
        page = client.get(s["url"]).content
        assert b"ASSESS-r2" in page and b"ASSESS-e" in page and b"STATEMENT-e" in page
        assert url.encode() not in page  # no form
    assert Assessment.objects.get(member=s["reviewer"]).assessment == "ASSESS-r2"
    # re-opening by the FO makes it writable again
    task.ends_at = timezone.now() + timedelta(days=1)
    task.save()
    assert reviewer.post(url, body("again")).status_code == 302


def test_final_statement_by_the_chair_in_its_window(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    chair, reviewer, support = (seat_client(s[r]) for r in ("chair", "reviewer", "support"))
    url = s["url"] + "final/"
    make_task(s["panel"], PanelTask.Kind.ASSESSMENT, ended=True)  # the review is done
    assert chair.post(url, FINAL).status_code == 403  # no task
    task = make_task(s["panel"], PanelTask.Kind.FINAL, open_=False)
    assert chair.post(url, FINAL).status_code == 403  # upcoming
    assert b"final-statement" not in chair.get(s["url"]).content  # nothing shown yet
    task.starts_at = timezone.now() - timedelta(hours=1)
    task.save()
    assert reviewer.post(url, FINAL).status_code == 403
    assert support.post(url, FINAL).status_code == 403
    assert chair.post(url, FINAL).status_code == 302
    final = FinalStatement.objects.get()
    assert final.author == s["chair"] and final.quality_grade == 5
    assert chair.post(url, {**FINAL, "final_grade": "10"}).status_code == 302
    assert FinalStatement.objects.get().final_grade == 10
    assert chair.post(url, {**FINAL, "merits": ""}, follow=True).status_code == 200
    assert FinalStatement.objects.get().merits == "m"
    for client in (reviewer, support):
        page = client.get(s["url"]).content
        assert b"Fund it" in page and b"10/10" in page and url.encode() not in page
    # the chair of another panel cannot touch it, and the window closes
    other_url = f"/panels/{s['panel'].pk}/applications/{s['unassigned_app'].pk}/final/"
    assert chair.post(other_url, FINAL).status_code == 302  # chair sees all applications
    task.ends_at = timezone.now() - timedelta(minutes=1)
    task.save()
    assert chair.post(url, FINAL).status_code == 403
    assert b"task closed" in chair.get(s["url"]).content


def test_supporting_admin_manages_the_schedule(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    support, reviewer = seat_client(s["support"]), seat_client(s["reviewer"])
    base = f"/panels/{s['panel'].pk}/"
    now = timezone.localtime()
    meeting = {
        "title": "Final meeting",
        "starts_at": now.strftime("%Y-%m-%dT%H:%M"),
        "ends_at": "",
        "location": "Zoom",
        "notes": "",
    }
    assert reviewer.get(base + "meetings/new/").status_code == 403
    assert reviewer.post(base + "meetings/new/", meeting).status_code == 403
    assert b"Add meeting" not in reviewer.get(base).content
    assert b"Add meeting" in support.get(base).content
    assert support.post(base + "meetings/new/", meeting).status_code == 302
    m = Meeting.objects.get()
    assert b"Final meeting" in reviewer.get(base).content
    assert (
        support.post(base + f"meetings/{m.pk}/edit/", {**meeting, "title": "Moved"}).status_code
        == 302
    )
    assert Meeting.objects.get().title == "Moved"
    task = {
        "kind": "other",
        "title": "Read everything",
        "starts_at": meeting["starts_at"],
        "ends_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
    }
    assert support.post(base + "tasks/new/", task).status_code == 302
    t = PanelTask.objects.get()
    assert reviewer.post(base + f"tasks/{t.pk}/delete/").status_code == 403
    assert support.post(base + f"tasks/{t.pk}/delete/").status_code == 302
    assert support.post(base + f"meetings/{m.pk}/delete/").status_code == 302
    assert not PanelTask.objects.exists() and not Meeting.objects.exists()


def test_removing_an_assignment_hides_the_application(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    reviewer = seat_client(s["reviewer"])
    assert reviewer.get(s["url"]).status_code == 200
    s["reviewer"].assignments.all().delete()
    assert reviewer.get(s["url"]).status_code == 404
    assert isinstance(s["app"], Application)


def test_final_statement_is_hidden_until_the_review_is_done(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    chair = seat_client(s["chair"])
    url = s["url"] + "final/"
    assessment = make_task(s["panel"], PanelTask.Kind.ASSESSMENT)
    make_task(s["panel"], PanelTask.Kind.FINAL, title="Final statement")  # open; review runs
    for client in (chair, seat_client(s["reviewer"])):
        assert b"Final statement" not in client.get(s["url"]).content
    assert chair.post(url, FINAL).status_code == 403
    # the assessment deadline passes: the form appears
    assessment.ends_at = timezone.now() - timedelta(minutes=1)
    assessment.save()
    assert url.encode() in chair.get(s["url"]).content
    assert chair.post(url, FINAL).status_code == 302


def test_fo_ending_the_review_early_opens_the_final_statement(
    make_grant: Any,
    make_panel: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
    make_task: Any,
    seat_client: Any,
) -> None:
    s = _setup(make_grant, make_panel, make_application, make_seat, assign)
    chair, reviewer = seat_client(s["chair"]), seat_client(s["reviewer"])
    make_task(s["panel"], PanelTask.Kind.ASSESSMENT)
    make_task(s["panel"], PanelTask.Kind.FINAL)
    url = s["url"] + "final/"
    assert chair.post(url, FINAL).status_code == 403
    panel = s["panel"]
    panel.review_closed_at = timezone.now()
    panel.save()
    assert url.encode() in chair.get(s["url"]).content
    assert chair.post(url, FINAL).status_code == 302
    # ending early also freezes assessments, as a passed deadline does
    body = {"assessment": "a", "preliminary_statement": "p", "preliminary_grade": "5"}
    assert reviewer.post(s["url"] + "assessment/", body).status_code == 403


def test_logged_out_page_uses_the_reviewer_design(review_site: None, db: None) -> None:
    response = Client().get("/logged-out/")
    assert response.status_code == 200
    assert b"You have been logged out" in response.content and b"it-reviewer" in response.content
