"""Review panel management on the staff site (fo1.it42.vr).

Every member can look; org admins manage. Payment information and passports of
reviewers are shown to admins only.
"""

from typing import Any

from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from it42.common.http import post_required
from it42.org.applications.models import Application
from it42.org.grants.models import Grant
from it42.org.members.access import admin_required, membership_of

from . import services
from .forms import MeetingForm, PanelForm, SeatForm, TaskForm
from .models import (
    Declaration,
    FinalStatement,
    Meeting,
    Panel,
    PanelMember,
    PanelTask,
    ReviewerProfile,
)


def _panel(panel_id: int) -> Panel:
    return get_object_or_404(Panel, pk=panel_id)


def _is_admin(request: HttpRequest) -> bool:
    membership = membership_of(request)
    return membership is not None and membership.is_admin


def panel_list(request: HttpRequest) -> HttpResponse:
    panels = Panel.objects.annotate(
        seat_count=Count("members", distinct=True), grant_count=Count("grants", distinct=True)
    )
    return render(request, "org/review/panels.html", {"panels": panels})


@admin_required
def panel_create(request: HttpRequest) -> HttpResponse:
    form = PanelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        panel = form.save(commit=False)
        panel.created_by = request.user
        panel.save()
        messages.success(request, f"Panel “{panel.name}” created. Add seats and grants.")
        return redirect("panel_detail", panel.pk)
    return render(request, "org/review/panel_form.html", {"form": form, "panel": None})


@admin_required
def panel_edit(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    form = PanelForm(request.POST or None, instance=panel)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Panel saved.")
        return redirect("panel_detail", panel.pk)
    return render(request, "org/review/panel_form.html", {"form": form, "panel": panel})


@post_required
@admin_required
def panel_delete(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    panel.delete()
    messages.success(request, f"Panel “{panel.name}” deleted.")
    return redirect("panel_list")


def panel_detail(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    now = timezone.now()
    applications = list(panel.applications())
    counts = services.assignment_counts(panel)
    linked = panel.grants.all()
    return render(
        request,
        "org/review/panel.html",
        {
            "panel": panel,
            "now": now,
            "seats": PanelMember.objects.filter(panel=panel).select_related("user"),
            "roles": PanelMember.Role.choices,
            "seat_form": SeatForm(panel),
            "grants": linked,
            "unlinked_grants": Grant.objects.exclude(pk__in=linked.values("pk"))
            .exclude(status=Grant.Status.DRAFT)
            .order_by("title"),
            "tasks": [(t, t.state(now)) for t in PanelTask.objects.filter(panel=panel)],
            "review_done": panel.review_done(now),
            "meetings": Meeting.objects.filter(panel=panel),
            "applications": [(a, counts.get(a.pk, 0)) for a in applications],
            "is_admin": _is_admin(request),
        },
    )


@post_required
@admin_required
def seat_add(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    form = SeatForm(panel, request.POST)
    if form.is_valid():
        seat = services.add_seat(panel, form.cleaned_data["email"], form.cleaned_data["role"])
        bound = " (already logged in, bound now)" if seat.user_id else ""
        messages.success(request, f"{seat.email} added as {seat.role_label}{bound}.")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, str(error))
    return redirect("panel_detail", panel.pk)


def _seat(panel_id: int, seat_id: int) -> PanelMember:
    return get_object_or_404(
        PanelMember.objects.select_related("panel", "user"), pk=seat_id, panel_id=panel_id
    )


@post_required
@admin_required
def seat_role(request: HttpRequest, panel_id: int, seat_id: int) -> HttpResponse:
    seat = _seat(panel_id, seat_id)
    role = request.POST.get("role", "")
    if role in PanelMember.Role.values:
        seat.role = role
        seat.save(update_fields=["role"])
        messages.success(request, f"{seat.email} is now {seat.role_label}.")
    else:
        messages.error(request, "Unknown role.")
    return redirect("panel_detail", panel_id)


@post_required
@admin_required
def seat_remove(request: HttpRequest, panel_id: int, seat_id: int) -> HttpResponse:
    seat = _seat(panel_id, seat_id)
    seat.delete()
    messages.success(request, f"{seat.email} removed from the panel, with their assignments.")
    return redirect("panel_detail", panel_id)


@admin_required
def seat_detail(request: HttpRequest, panel_id: int, seat_id: int) -> HttpResponse:
    seat = _seat(panel_id, seat_id)
    profile = ReviewerProfile.objects.filter(user_id=seat.user_id).first() if seat.user_id else None
    return render(
        request,
        "org/review/seat.html",
        {
            "panel": seat.panel,
            "seat": seat,
            "profile": profile,
            "declarations": Declaration.objects.filter(member=seat).select_related(
                "application", "application__grant"
            ),
        },
    )


@admin_required
def seat_passport(request: HttpRequest, panel_id: int, seat_id: int) -> FileResponse:
    seat = _seat(panel_id, seat_id)
    profile = ReviewerProfile.objects.filter(user_id=seat.user_id).first() if seat.user_id else None
    if profile is None or not profile.passport:
        raise Http404("No passport uploaded")
    return FileResponse(
        profile.passport.open("rb"),
        as_attachment=True,
        filename=profile.passport_name or "passport.pdf",
        content_type="application/pdf",
    )


@post_required
@admin_required
def grant_link(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    grant = get_object_or_404(Grant, pk=request.POST.get("grant_id", "0"))
    if grant.status == Grant.Status.DRAFT:
        messages.error(request, "Publish the grant before attaching it to a panel.")
    else:
        panel.grants.add(grant)
        messages.success(request, f"“{grant.title}” attached to the panel.")
    return redirect("panel_detail", panel.pk)


@post_required
@admin_required
def grant_unlink(request: HttpRequest, panel_id: int, grant_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    grant = get_object_or_404(panel.grants, pk=grant_id)
    services.unlink_grant(panel, grant.pk)
    messages.success(request, f"“{grant.title}” detached; its assignments were removed.")
    return redirect("panel_detail", panel.pk)


def _schedule_form(
    request: HttpRequest,
    panel: Panel,
    form: Any,
    template: str,
    title: str,
) -> HttpResponse:
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.panel = panel
        item.save()
        messages.success(request, f"{title} saved.")
        return redirect("panel_detail", panel.pk)
    return render(request, template, {"form": form, "panel": panel, "title": title})


@post_required
@admin_required
def review_close(request: HttpRequest, panel_id: int) -> HttpResponse:
    """End the review phase now and move on to the final statement.

    Assessments freeze and become visible to the panel; an upcoming final-statement task
    starts now.
    """
    panel = _panel(panel_id)
    now = timezone.now()
    if panel.review_done(now):
        messages.info(request, "The review is already done.")
        return redirect("panel_detail", panel.pk)
    with transaction.atomic():
        panel.review_closed_at = now
        panel.save(update_fields=["review_closed_at", "updated_at"])
        final = panel.task(PanelTask.Kind.FINAL)
        if final is not None and final.starts_at > now:
            final.starts_at = now
            final.save(update_fields=["starts_at"])
    if final is None:
        messages.warning(
            request, "Review ended. Add a final-statement task so the chairperson can write."
        )
    elif final.has_ended(now):
        messages.warning(
            request, "Review ended, but the final-statement task is over; move its end date."
        )
    else:
        messages.success(request, "Review ended. The final-statement phase is open.")
    return redirect("panel_detail", panel.pk)


@post_required
@admin_required
def review_reopen(request: HttpRequest, panel_id: int) -> HttpResponse:
    """Undo an early end; the assessment task's dates rule again."""
    panel = _panel(panel_id)
    if FinalStatement.objects.filter(panel=panel).exists():
        messages.error(request, "Final statements have been written; the review cannot reopen.")
    else:
        panel.review_closed_at = None
        panel.save(update_fields=["review_closed_at", "updated_at"])
        messages.success(request, "Early end undone. The assessment task's dates apply again.")
    return redirect("panel_detail", panel.pk)


@admin_required
def task_create(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    form = TaskForm(panel, request.POST or None)
    return _schedule_form(request, panel, form, "org/review/task_form.html", "Task")


@admin_required
def task_edit(request: HttpRequest, panel_id: int, task_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    task = get_object_or_404(PanelTask, pk=task_id, panel=panel)
    form = TaskForm(panel, request.POST or None, instance=task)
    return _schedule_form(request, panel, form, "org/review/task_form.html", "Task")


@post_required
@admin_required
def task_delete(request: HttpRequest, panel_id: int, task_id: int) -> HttpResponse:
    task = get_object_or_404(PanelTask, pk=task_id, panel_id=panel_id)
    task.delete()
    messages.success(request, f"Task “{task.title}” deleted.")
    return redirect("panel_detail", panel_id)


@admin_required
def meeting_create(request: HttpRequest, panel_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    form = MeetingForm(request.POST or None)
    return _schedule_form(request, panel, form, "org/review/meeting_form.html", "Meeting")


@admin_required
def meeting_edit(request: HttpRequest, panel_id: int, meeting_id: int) -> HttpResponse:
    panel = _panel(panel_id)
    meeting = get_object_or_404(Meeting, pk=meeting_id, panel=panel)
    form = MeetingForm(request.POST or None, instance=meeting)
    return _schedule_form(request, panel, form, "org/review/meeting_form.html", "Meeting")


@post_required
@admin_required
def meeting_delete(request: HttpRequest, panel_id: int, meeting_id: int) -> HttpResponse:
    meeting = get_object_or_404(Meeting, pk=meeting_id, panel_id=panel_id)
    meeting.delete()
    messages.success(request, f"Meeting “{meeting.title}” deleted.")
    return redirect("panel_detail", panel_id)


def _panel_application(panel_id: int, application_id: int) -> tuple[Panel, Application]:
    panel = _panel(panel_id)
    application = get_object_or_404(panel.applications(), pk=application_id)
    return panel, application


def panel_application(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    panel, application = _panel_application(panel_id, application_id)
    now = timezone.now()
    review = services.application_review(panel, application, now)
    assigned_ids = {m.pk for m in review.assigned}
    return render(
        request,
        "org/review/application.html",
        {
            "panel": panel,
            "application": application,
            "review": review,
            "show_final": panel.final_phase_started(now),
            "seats": [
                (seat, seat.pk in assigned_ids)
                for seat in PanelMember.objects.filter(
                    panel=panel, role__in=PanelMember.REVIEWING_ROLES
                ).select_related("user")
            ],
            "is_admin": _is_admin(request),
        },
    )


@post_required
@admin_required
def assign(request: HttpRequest, panel_id: int, application_id: int) -> HttpResponse:
    panel, application = _panel_application(panel_id, application_id)
    seat_ids = {
        int(key.removeprefix("seat_"))
        for key, value in request.POST.items()
        if key.startswith("seat_") and key.removeprefix("seat_").isdigit() and value
    }
    count = services.set_assignments(panel, application, seat_ids)
    messages.success(request, f"{count} reviewer{'s' if count != 1 else ''} assigned.")
    return redirect("panel_application", panel.pk, application.pk)
