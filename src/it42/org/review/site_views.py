"""The reviewer site (fo1-review.it42.vr): only reviewer work, nothing else.

``ReviewerGateMiddleware`` guarantees a logged-in user with at least one seat; every
view here then resolves the seat on the requested panel and applies ``access`` rules.
Applications are shown with their answers and PDFs, never with the org's status
controls, applicant questions or review notes.
"""

from datetime import datetime
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import dateformat, timezone

from it42.common.agenda import Deadline, agenda
from it42.common.formschema import labelled_answers
from it42.common.http import post_required
from it42.org.applications.models import Application, ApplicationDocument

from . import access, services
from .forms import (
    AssessmentForm,
    DeclarationForm,
    FinalStatementForm,
    MeetingForm,
    PassportForm,
    PaymentForm,
    TaskForm,
)
from .models import (
    Assessment,
    Assignment,
    Declaration,
    FinalStatement,
    Meeting,
    Panel,
    PanelMember,
    PanelTask,
    ReviewerNote,
    ReviewerProfile,
)


def _seat(request: HttpRequest, panel_id: int) -> PanelMember:
    panel = get_object_or_404(Panel, pk=panel_id)
    return access.seat_or_404(panel, request.user)


def _application(seat: PanelMember, application_id: int) -> Application:
    return get_object_or_404(access.visible_applications(seat.panel, seat), pk=application_id)


def _pct(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


def _phase(panel: Panel, tasks: list[PanelTask], now: datetime) -> tuple[str, str]:
    """Status pill (tone, label) of a panel card, from its review tasks."""
    by_kind = {t.kind: t for t in tasks}
    final = by_kind.get(PanelTask.Kind.FINAL)
    if panel.review_done(now):
        if final is not None and final.is_open(now):
            return "yellow", "Final statements"
        if final is not None and final.has_ended(now):
            return "solid-green", "Completed"
        return "green", "Scores shared"
    assessment = by_kind.get(PanelTask.Kind.ASSESSMENT)
    if assessment is not None and assessment.is_open(now):
        return "blue", "Reviewing"
    conflict = by_kind.get(PanelTask.Kind.CONFLICT)
    if conflict is not None and conflict.is_open(now):
        return "peach", "Conflict check"
    upcoming = [t for t in tasks if t.starts_at > now]
    if upcoming:
        start = timezone.localtime(min(t.starts_at for t in upcoming))
        return "grey", f"Starts {dateformat.format(start, 'j M')}"
    return "grey", "No open task"


def _progress(seat: PanelMember) -> dict[str, Any]:
    """The seat's and the whole panel's review counts (Dashboard / Reviewer)."""
    panel = seat.panel
    mine = Assignment.objects.filter(member=seat).count()
    done = Assessment.objects.filter(member=seat).count()
    panel_total = Assignment.objects.filter(member__panel=panel).count()
    panel_done = Assessment.objects.filter(member__panel=panel).count()
    return {
        "mine": mine,
        "done": min(done, mine) if mine else done,
        "left": max(mine - done, 0),
        "pct": _pct(done, mine),
        "panel_total": panel_total,
        "panel_done": panel_done,
        "panel_pct": _pct(panel_done, panel_total),
        "declared": Declaration.objects.filter(member=seat).count(),
    }


def _panel_summary(seat: PanelMember, now: datetime) -> dict[str, Any]:
    panel = seat.panel
    tasks = list(PanelTask.objects.filter(panel=panel))
    members = list(PanelMember.objects.filter(panel=panel).select_related("user"))
    chair = next((m for m in members if m.is_chair), None)
    tone, label = _phase(panel, tasks, now)
    open_tasks = [t for t in tasks if t.is_open(now)]
    return {
        "seat": seat,
        "panel": panel,
        "members": members,
        "reviewers": [m for m in members if m.reviews],
        "chair": "You" if chair is not None and chair.pk == seat.pk else chair,
        "next_meeting": Meeting.objects.filter(panel=panel, starts_at__gte=now).first(),
        "open_tasks": open_tasks,
        "active": bool(open_tasks),
        "assessment": panel.task(PanelTask.Kind.ASSESSMENT),
        "application_count": access.visible_applications(panel, seat).count(),
        "tone": tone,
        "phase": label,
        "progress": _progress(seat),
    }


def my_panels(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    cards = [_panel_summary(seat, now) for seat in access.seats_of(request)]
    meetings = [c["next_meeting"] for c in cards if c["next_meeting"] is not None]
    deadlines = [
        Deadline(t.title, c["panel"].name, timezone.localdate(t.ends_at), "task")
        for c in cards
        for t in PanelTask.objects.filter(panel=c["panel"])
    ] + [
        Deadline(m.title, c["panel"].name, timezone.localdate(m.starts_at), "meeting")
        for c in cards
        for m in Meeting.objects.filter(panel=c["panel"])
    ]
    return render(
        request,
        "org/review/site/panels.html",
        {
            "active": [c for c in cards if c["active"]],
            "other": [c for c in cards if not c["active"]],
            "cards": cards,
            "left": sum(c["progress"]["left"] for c in cards),
            "next_meeting": min(meetings, key=lambda m: m.starts_at, default=None),
            "now": now,
            **agenda(timezone.localdate(), deadlines),
        },
    )


def _timeline(
    tasks: list[PanelTask], meetings: list[Meeting], now: datetime
) -> list[dict[str, Any]]:
    """Important dates of a panel: each task's deadline and each meeting, in order, with
    the first one still ahead marked as next."""
    items: list[dict[str, Any]] = [
        {"when": t.ends_at, "title": t.title, "detail": t.kind_label, "kind": "task"} for t in tasks
    ]
    items += [
        {
            "when": m.starts_at,
            "title": m.title,
            "detail": m.location or "Meeting",
            "kind": "meeting",
        }
        for m in meetings
    ]
    items.sort(key=lambda i: i["when"])
    upcoming = [i for i in items if i["when"] >= now]
    for item in items:
        item["state"] = "past" if item["when"] < now else "future"
    if upcoming:
        upcoming[0]["state"] = "next"
    return items


def panel_detail(request: HttpRequest, panel_id: int) -> HttpResponse:
    seat = _seat(request, panel_id)
    panel = seat.panel
    now = timezone.now()
    applications = list(access.visible_applications(panel, seat))
    states = services.seat_states(seat, applications)
    tasks = list(PanelTask.objects.filter(panel=panel))
    meetings = list(Meeting.objects.filter(panel=panel))
    shared = panel.assessments_shared(now)
    ids = [a.pk for a in applications]
    grades = dict(
        Assessment.objects.filter(member=seat, application_id__in=ids).values_list(
            "application_id", "preliminary_grade"
        )
    )
    panel_scores: dict[int, list[int]] = {}
    latest: list[Assessment] = []
    if shared:
        for a in Assessment.objects.filter(member__panel=panel, application_id__in=ids):
            panel_scores.setdefault(a.application_id, []).append(a.preliminary_grade)
        latest = list(
            Assessment.objects.filter(member__panel=panel, application_id__in=ids)
            .exclude(member=seat)
            .select_related("member", "member__user", "application")
            .order_by("-updated_at")[:3]
        )
    rows: list[dict[str, Any]] = [
        {
            "application": a,
            "state": states[a.pk],
            "grade": grades.get(a.pk),
            "scores": panel_scores.get(a.pk, []),
            "avg": sum(panel_scores[a.pk]) / len(panel_scores[a.pk])
            if panel_scores.get(a.pk)
            else None,
        }
        for a in applications
    ]
    # To do first, then written; the assigned ones before the rest.
    rows.sort(key=lambda r: (not r["state"]["assigned"], r["state"]["assessed"]))
    summary = _panel_summary(seat, now)
    return render(
        request,
        "org/review/site/panel.html",
        {
            **summary,
            "now": now,
            "shared": shared,
            "tasks": [(t, t.state(now)) for t in tasks],
            "meetings": meetings,
            "timeline": _timeline(tasks, meetings, now),
            "applications": rows,
            "latest": latest,
            "manages_schedule": access.can_manage_schedule(seat),
        },
    )


def application_detail(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    seat = _seat(request, panel_id)
    panel = seat.panel
    application = _application(seat, application_id)
    now = timezone.now()
    review = services.application_review(panel, application, now)
    my_declaration = Declaration.objects.filter(member=seat, application=application).first()
    my_assessment = Assessment.objects.filter(member=seat, application=application).first()
    assigned = access.is_assigned(seat, application)
    final_writable = access.can_write_final(seat, now)
    return render(
        request,
        "org/review/site/application.html",
        {
            "panel": panel,
            "seat": seat,
            "application": application,
            "answers": labelled_answers(application.grant.form_schema, application.answers),
            "documents": ApplicationDocument.objects.filter(application=application),
            "assigned": assigned,
            "review": review,
            "tasks": {
                "conflict": panel.task(PanelTask.Kind.CONFLICT),
                "assessment": panel.task(PanelTask.Kind.ASSESSMENT),
                "final": panel.task(PanelTask.Kind.FINAL),
            },
            "now": now,
            "my_declaration": my_declaration,
            "declaration_form": DeclarationForm(instance=my_declaration)
            if access.can_declare(seat, application, now)
            else None,
            "my_assessment": my_assessment,
            "assessment_form": AssessmentForm(instance=my_assessment)
            if access.can_assess(seat, application, now)
            else None,
            "final_form": FinalStatementForm(instance=review.final) if final_writable else None,
            "show_final": panel.final_phase_started(now),
            "other_assessments": [a for a in review.assessments if a.member_id != seat.pk],
            "declarations": review.declarations if access.can_see_declarations(seat) else [],
            "grade_values": range(11),
            "notes": ReviewerNote.objects.filter(member=seat, application=application),
            "key_dates": _key_dates(panel, application, now),
        },
    )


def _key_dates(panel: Panel, application: Application, now: datetime) -> list[dict[str, Any]]:
    """The call's deadline and the panel's schedule, for the Grant details tab. The
    final-statement task stays out until its phase has started (access.py)."""
    today = timezone.localdate()
    dates: list[dict[str, Any]] = [
        {"day": application.grant.deadline, "text": "Applications close", "now": False}
    ]
    tasks = PanelTask.objects.filter(panel=panel)
    if not panel.final_phase_started(now):
        tasks = tasks.exclude(kind=PanelTask.Kind.FINAL)
    for task in tasks:
        start, end = timezone.localdate(task.starts_at), timezone.localdate(task.ends_at)
        dates.append({"day": end, "text": f"Last day: {task.title}", "now": start <= today <= end})
    for meeting in Meeting.objects.filter(panel=panel):
        dates.append(
            {"day": timezone.localdate(meeting.starts_at), "text": meeting.title, "now": False}
        )
    return sorted(dates, key=lambda d: d["day"])


MAX_NOTE = 5000


@post_required
def add_note(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    """My notes: private to the seat that writes them (access.py has no reader for them)."""
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    text = request.POST.get("text", "").strip()
    if not text or len(text) > MAX_NOTE:
        messages.error(request, f"Write 1-{MAX_NOTE} characters.")
    else:
        ReviewerNote.objects.create(member=seat, application=application, text=text)
        messages.success(request, "Note saved. Only you can see it.")
    return redirect(reverse("review_application", args=[panel_id, application_id]) + "#notes")


@post_required
def delete_note(
    request: HttpRequest, panel_id: int, application_id: int, note_id: int
) -> HttpResponse:
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    get_object_or_404(ReviewerNote, pk=note_id, member=seat, application=application).delete()
    messages.success(request, "Note deleted.")
    return redirect(reverse("review_application", args=[panel_id, application_id]) + "#notes")


@post_required
def declare(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    if not access.can_declare(seat, application, timezone.now()):
        raise PermissionDenied("The conflict of interest task is not open for you.")
    instance = Declaration.objects.filter(member=seat, application=application).first()
    form = DeclarationForm(request.POST, instance=instance)
    if form.is_valid():
        declaration = form.save(commit=False)
        declaration.member = seat
        declaration.application = application
        declaration.save()
        messages.success(request, "Conflict of interest and competence saved.")
    else:
        _report(request, form)
    return redirect("review_application", panel_id, application_id)


@post_required
def assess(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    if not access.can_assess(seat, application, timezone.now()):
        raise PermissionDenied("The assessment task is not open for you.")
    instance = Assessment.objects.filter(member=seat, application=application).first()
    form = AssessmentForm(request.POST, instance=instance)
    if form.is_valid():
        assessment = form.save(commit=False)
        assessment.member = seat
        assessment.application = application
        assessment.save()
        messages.success(request, "Assessment saved. Only you can see it until the deadline.")
    else:
        _report(request, form)
    return redirect("review_application", panel_id, application_id)


@post_required
def final(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    if not access.can_write_final(seat, timezone.now()):
        raise PermissionDenied(
            "Only a chairperson can write the final statement, once the review is done."
        )
    instance = FinalStatement.objects.filter(panel=seat.panel, application=application).first()
    form = FinalStatementForm(request.POST, instance=instance)
    if form.is_valid():
        statement = form.save(commit=False)
        statement.panel = seat.panel
        statement.application = application
        statement.author = seat
        statement.save()
        messages.success(request, "Final statement saved.")
    else:
        _report(request, form)
    return redirect("review_application", panel_id, application_id)


def _report(request: HttpRequest, form: Any) -> None:
    for field, errors in form.errors.items():
        label = form.fields[field].label if field in form.fields else ""
        for error in errors:
            messages.error(request, f"{label}: {error}" if label else str(error))


def document(
    request: HttpRequest, panel_id: int, application_id: int, document_id: int
) -> FileResponse:
    seat = _seat(request, panel_id)
    application = _application(seat, application_id)
    doc = get_object_or_404(ApplicationDocument, pk=document_id, application=application)
    return FileResponse(
        doc.file.open("rb"),
        as_attachment=True,
        filename=doc.original_name,
        content_type="application/pdf",
    )


def _schedule_seat(request: HttpRequest, panel_id: int) -> PanelMember:
    seat = _seat(request, panel_id)
    if not access.can_manage_schedule(seat):
        raise PermissionDenied("Only supporting admins manage meetings and tasks.")
    return seat


def _schedule_form(
    request: HttpRequest, seat: PanelMember, form: Any, template: str, title: str
) -> HttpResponse:
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.panel = seat.panel
        item.save()
        messages.success(request, f"{title} saved.")
        return redirect("review_panel", seat.panel.pk)
    return render(request, template, {"form": form, "panel": seat.panel, "title": title})


def meeting_create(request: HttpRequest, panel_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    form = MeetingForm(request.POST or None)
    return _schedule_form(request, seat, form, "org/review/site/schedule_form.html", "Meeting")


def meeting_edit(request: HttpRequest, panel_id: int, meeting_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    meeting = get_object_or_404(Meeting, pk=meeting_id, panel=seat.panel)
    form = MeetingForm(request.POST or None, instance=meeting)
    return _schedule_form(request, seat, form, "org/review/site/schedule_form.html", "Meeting")


@post_required
def meeting_delete(request: HttpRequest, panel_id: int, meeting_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    meeting = get_object_or_404(Meeting, pk=meeting_id, panel=seat.panel)
    meeting.delete()
    messages.success(request, f"Meeting “{meeting.title}” deleted.")
    return redirect("review_panel", panel_id)


def task_create(request: HttpRequest, panel_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    form = TaskForm(seat.panel, request.POST or None)
    return _schedule_form(request, seat, form, "org/review/site/schedule_form.html", "Task")


def task_edit(request: HttpRequest, panel_id: int, task_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    task = get_object_or_404(PanelTask, pk=task_id, panel=seat.panel)
    form = TaskForm(seat.panel, request.POST or None, instance=task)
    return _schedule_form(request, seat, form, "org/review/site/schedule_form.html", "Task")


@post_required
def task_delete(request: HttpRequest, panel_id: int, task_id: int) -> HttpResponse:
    seat = _schedule_seat(request, panel_id)
    task = get_object_or_404(PanelTask, pk=task_id, panel=seat.panel)
    task.delete()
    messages.success(request, f"Task “{task.title}” deleted.")
    return redirect("review_panel", panel_id)


def _profile(request: HttpRequest) -> ReviewerProfile:
    profile, _ = ReviewerProfile.objects.get_or_create(user_id=request.user.pk)
    return profile


def profile(request: HttpRequest) -> HttpResponse:
    instance = _profile(request)
    form = PaymentForm(instance=instance)
    upload = PassportForm()
    if request.method == "POST" and "save_profile" in request.POST:
        form = PaymentForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile saved.")
            return redirect("review_profile")
    elif request.method == "POST" and "upload" in request.POST:
        upload = PassportForm(request.POST, request.FILES)
        if upload.is_valid():
            original = upload.cleaned_data["passport"].name[:255]
            instance.clear_passport()
            instance.passport_name = original
            instance.passport_sha256 = upload.sha256
            instance.passport_size = len(upload.content)
            instance.passport_uploaded_at = timezone.now()
            instance.passport.save(original, ContentFile(upload.content), save=True)
            messages.success(request, f"Uploaded {original}.")
            return redirect("review_profile")
    return render(
        request,
        "org/review/site/profile.html",
        {"form": form, "upload": upload, "profile": instance},
    )


def passport(request: HttpRequest) -> FileResponse:
    instance = _profile(request)
    if not instance.passport:
        raise Http404("No passport uploaded")
    return FileResponse(
        instance.passport.open("rb"),
        as_attachment=True,
        filename=instance.passport_name or "passport.pdf",
        content_type="application/pdf",
    )


@post_required
def passport_delete(request: HttpRequest) -> HttpResponse:
    instance = _profile(request)
    instance.clear_passport()
    instance.save()
    messages.success(request, "Passport copy removed.")
    return redirect("review_profile")
