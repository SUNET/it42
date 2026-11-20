from django.contrib import messages
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import dateformat, timezone

from it42.common.formschema import labelled_answers
from it42.common.http import board_card, post_required
from it42.common.statuses import (
    ENDED_BEFORE_REVIEW,
    ORG_SETTABLE_STATUSES,
    ApplicationStatus,
)
from it42.org.accounts.models import User
from it42.org.grants.models import Grant
from it42.org.review.models import Assignment
from it42.org.review.services import panels_for_application, score_summaries

from . import activity, services
from .models import Application, ApplicationDocument, Question, ReviewNote

MAX_TEXT = 5000
REVIEW_STATUSES = (ApplicationStatus.UNDER_REVIEW, ApplicationStatus.NEEDS_INFO)


def _user(request: HttpRequest) -> User:
    user = request.user
    assert isinstance(user, User)  # noqa: S101 (the membership gate ran first)
    return user


def _text(request: HttpRequest) -> str | None:
    text = request.POST.get("text", "").strip()
    if not text or len(text) > MAX_TEXT:
        messages.error(request, f"Write 1-{MAX_TEXT} characters.")
        return None
    return text


@board_card
def for_grant(request: HttpRequest, grant_id: int) -> HttpResponse:
    """Compare applicants (Grants / Views / Granter - Compare applicants): every
    application of the grant with its review progress, best shared score first, filtered
    by status with ``?status=``."""
    grant = get_object_or_404(Grant, pk=grant_id)
    applications = list(Application.objects.filter(grant=grant))
    scores = score_summaries(applications, timezone.now())
    counts: dict[str, int] = {}
    for application in applications:
        counts[application.status] = counts.get(application.status, 0) + 1
    tabs = [
        {"value": status.value, "label": status.label, "count": counts[status.value]}
        for status in ApplicationStatus
        if status.value in counts
    ]
    current = request.GET.get("status", "")
    if current not in counts:
        current = ""
    shown = [a for a in applications if not current or a.status == current]
    shown.sort(key=lambda a: a.submitted_at, reverse=True)
    shown.sort(key=lambda a: -(scores[a.pk].average or -1))
    return render(
        request,
        "org/applications/for_grant.html",
        {
            "grant": grant,
            "total": len(applications),
            "tabs": tabs,
            "current": current,
            "rows": [(a, scores[a.pk]) for a in shown],
        },
    )


def _steps(application: Application, assigned: int) -> tuple[int, list[dict[str, str]]]:
    """The stages of Card detail (granter) and the current one (1-based). Applications
    naming an administrating organisation get an extra "Organisation sign-off" stage."""
    status = ApplicationStatus(application.status)
    decided = status in (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED)
    signing = bool(application.research_org)
    if not application.reviewable:
        stage = 2
    elif decided:
        stage = 4
    elif status in (ApplicationStatus.UNDER_REVIEW, ApplicationStatus.NEEDS_INFO):
        stage = 3
    else:
        stage = 2 if assigned else 1
    if signing and application.reviewable:
        stage += 1
    stages = [
        ("Received", dateformat.format(timezone.localtime(application.received_at), "j M")),
        ("Reviewers assigned", f"{assigned} reviewer{'s' if assigned != 1 else ''}"),
        ("Review process", str(status.label) if status in REVIEW_STATUSES else ""),
        ("Granted / Declined", str(status.label) if decided else ""),
    ]
    if signing:
        if application.reviewable and application.signed_at:
            signed = "Signed " + dateformat.format(timezone.localtime(application.signed_at), "j M")
        elif application.reviewable:
            signed = "Signed"
        else:
            signed = str(status.label)
        stages.insert(1, ("Organisation sign-off", signed))
    steps = []
    for index, (label, note) in enumerate(stages, start=1):
        state = "done" if index < stage else "current" if index == stage else "todo"
        if index == len(stages) and status == ApplicationStatus.REJECTED:
            state = "declined"
        if index == stage and status in ENDED_BEFORE_REVIEW:
            state = "declined"
        steps.append({"label": label, "note": note if index <= stage else "", "state": state})
    return stage, steps


@board_card
def detail(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(
        Application.objects.select_related("grant", "grant__created_by", "decided_by"),
        pk=application_id,
    )
    assigned = Assignment.objects.filter(application=application).count()
    stage, steps = _steps(application, assigned)
    reviews = panels_for_application(application, timezone.now())
    return render(
        request,
        "org/applications/detail.html",
        {
            "application": application,
            "answers": labelled_answers(application.grant.form_schema, application.answers),
            "documents": ApplicationDocument.objects.filter(application=application),
            "questions": Question.objects.filter(application=application).select_related(
                "asked_by"
            ),
            "notes": ReviewNote.objects.filter(application=application).select_related("author"),
            "statuses": [(s.value, s.label) for s in ORG_SETTABLE_STATUSES],
            "reviews": reviews,
            "summary": activity.review_summary(application, reviews),
            "months": activity.activity(application, reviews),
            "people": activity.people(application, reviews),
            "key_dates": activity.key_dates(application),
            "sections": activity.form_sections(application.grant.form_schema),
            "stage": stage,
            "steps": steps,
            "assigned": assigned,
        },
    )


def download(request: HttpRequest, application_id: int, document_id: int) -> FileResponse:
    document = get_object_or_404(ApplicationDocument, pk=document_id, application_id=application_id)
    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=document.original_name,
        content_type="application/pdf",
    )


@post_required
def set_status(request: HttpRequest, application_id: int) -> HttpResponse:
    get_object_or_404(Application, pk=application_id)
    try:
        application = services.change_status(
            application_id, request.POST.get("status", ""), _user(request)
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Status is now {ApplicationStatus(application.status).label}.")
    return redirect("application_detail", application_id)


@post_required
def ask(request: HttpRequest, application_id: int) -> HttpResponse:
    get_object_or_404(Application, pk=application_id)
    if text := _text(request):
        try:
            services.ask_question(application_id, _user(request), text)
        except services.NotReviewable as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Question sent to the applicant.")
    return redirect("application_detail", application_id)


@post_required
def note(request: HttpRequest, application_id: int) -> HttpResponse:
    get_object_or_404(Application, pk=application_id)
    if text := _text(request):
        services.add_note(application_id, _user(request), text)
        messages.success(request, "Note added. Only Org members can see it.")
    return redirect("application_detail", application_id)
