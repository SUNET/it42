from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from it42.common import research_orgs
from it42.common.activity import Event, Month, by_month
from it42.common.formpresentation import application_presentation
from it42.common.formschema import (
    answers_to_json,
    labelled_answers,
)
from it42.common.http import post_required
from it42.common.statuses import ENDED_BEFORE_REVIEW, ApplicationStatus
from it42.core.accounts.models import User
from it42.core.catalog.models import PublicGrant
from it42.core.catalog.views import is_open

from . import services
from .forms import application_form
from .models import ApplicationCopy, ApplicationDraft, QuestionCopy, StatusChange


def _user(request: HttpRequest) -> User:
    user = request.user
    assert isinstance(user, User)  # noqa: S101 (login_required ran first)
    return user


def raw_values(form: forms.BaseForm, data: QueryDict) -> dict[str, Any]:
    """The posted values as each field's widget reads them, for a draft: kept as typed,
    without validation, so incomplete or invalid answers can be saved and shown again."""
    values = {}
    for name, form_field in form.fields.items():
        value = form_field.widget.value_from_datadict(data, {}, form.add_prefix(name))
        values[name] = value
    return values


@login_required
def apply(request: HttpRequest, org_slug: str, grant_id: str) -> HttpResponse:
    grant = get_object_or_404(PublicGrant, org_slug=org_slug, grant_public_id=grant_id)
    user = _user(request)
    existing = (
        ApplicationCopy.objects.filter(user=user, grant=grant)
        .exclude(status__in=ENDED_BEFORE_REVIEW)
        .first()
    )
    autosave = request.method == "POST" and request.POST.get("autosave") == "1"
    if existing:
        if autosave:
            return JsonResponse(
                {"error": "This application has already been submitted."}, status=409
            )
        messages.info(request, "You have already applied to this grant.")
        return redirect("my_application", existing.public_id)
    if not is_open(grant):
        if autosave:
            return JsonResponse(
                {"error": "This call has closed. Your changes were not saved."}, status=409
            )
        messages.error(request, "This grant is closed for applications.")
        return redirect("grant_detail", org_slug, grant_id)
    draft = ApplicationDraft.objects.filter(user=user, grant=grant).first()
    # The applicant's name and email (base fields every form keeps; the applicant can
    # still change them), then whatever the draft holds.
    initial: dict[str, Any] = {
        "applicant_name": services.applicant_name(user),
        "applicant_email": user.email,
    }
    if draft:
        initial.update(draft.data)
    form_class = application_form(grant.form_schema)
    if request.method == "POST" and ("save_draft" in request.POST or autosave):
        unbound = form_class(user_id=user.pk)
        saved = services.save_draft(user, grant, raw_values(unbound, request.POST))
        if autosave:
            return JsonResponse({"saved_at": saved.updated_at.isoformat()})
        messages.success(request, "Your draft was saved. Nothing is sent until you submit it.")
        return redirect("apply", org_slug, grant_id)
    form = form_class(request.POST or None, user_id=user.pk, initial=initial)
    confirm_missing = request.method == "POST" and not request.POST.get("confirm")
    if confirm_missing:
        messages.error(request, "Confirm that your application is complete before you submit it.")
    if request.method == "POST" and form.is_valid() and not confirm_missing:
        data = dict(form.cleaned_data)
        documents = data.pop("documents")
        try:
            application = services.submit(user, grant, answers_to_json(data), documents)
        except IntegrityError:
            messages.info(request, "You have already applied to this grant.")
            return redirect("grant_detail", org_slug, grant_id)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Your application to {grant.org_name} was submitted.")
            return redirect("my_application", application.public_id)
    return render(
        request,
        "core/applications/apply.html",
        {
            "grant": grant,
            "form": form,
            **application_presentation(grant.form_schema, form),
            "title": grant.title,
            "description": grant.description,
            "org_name": grant.org_name,
            "confirm_missing": confirm_missing,
            "draft": draft,
        },
    )


@post_required
@login_required
def delete_draft(request: HttpRequest, draft_id: int) -> HttpResponse:
    draft = get_object_or_404(ApplicationDraft, pk=draft_id, user=_user(request))
    title = draft.grant.title
    draft.delete()
    messages.success(request, f"Your draft for {title} was deleted.")
    return redirect("my_applications")


S = ApplicationStatus


@dataclass
class Card:
    application: ApplicationCopy
    questions: int
    open_questions: int


@dataclass
class Column:
    """One board column (Dashboard / Applicant) and the statuses it collects."""

    key: str
    title: str
    statuses: tuple[str, ...]
    cards: list[Card] = field(default_factory=list)


def board_columns() -> list[Column]:
    """Drafts, then the sent applications until a decision (Dashboard / Applicant)."""
    return [
        Column("draft", "Application draft", ()),
        Column(
            "submitted",
            "Application submitted",
            (S.SUBMITTED, S.AWAITING_SIGNATURE, S.RECEIVED, S.UNDER_REVIEW, S.NEEDS_INFO),
        ),
        Column(
            "decision", "Granted / Declined", (S.APPROVED, S.REJECTED, S.RO_DECLINED, S.RO_EXPIRED)
        ),
    ]


@dataclass
class Note:
    """An entry of the right-hand activity feed."""

    when: datetime
    text: str
    icon: str
    application: ApplicationCopy


def activity_feed(user: User, limit: int = 6) -> list[Note]:
    notes = [
        Note(
            c.changed_at,
            f"{c.application.grant.title}: {ApplicationStatus(c.status).label.lower()}.",
            "file-text",
            c.application,
        )
        for c in StatusChange.objects.filter(application__user=user)
        .select_related("application__grant")
        .order_by("-changed_at")[:limit]
    ]
    notes += [
        Note(
            q.asked_at,
            f"{q.application.grant.org_name} asked a question about {q.application.grant.title}.",
            "chat-circle",
            q.application,
        )
        for q in QuestionCopy.objects.filter(application__user=user)
        .select_related("application__grant")
        .order_by("-asked_at")[:limit]
    ]
    return sorted(notes, key=lambda n: n.when, reverse=True)[:limit]


SORTS = {"recent": "-submitted_at", "deadline": "grant__deadline"}


@login_required
def my_applications(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    sort = request.GET.get("sort", "recent")
    if sort not in SORTS:
        sort = "recent"
    applications = list(
        ApplicationCopy.objects.filter(user=user).select_related("grant").order_by(SORTS[sort])
    )
    open_questions: dict[int, int] = {}
    question_counts: dict[int, int] = {}
    for q in QuestionCopy.objects.filter(application__user=user):
        question_counts[q.application_id] = question_counts.get(q.application_id, 0) + 1
        if not q.answered_at:
            open_questions[q.application_id] = open_questions.get(q.application_id, 0) + 1
    columns = board_columns()
    for app in applications:
        card = Card(app, question_counts.get(app.pk, 0), open_questions.get(app.pk, 0))
        for column in columns:
            if app.status in column.statuses:
                column.cards.append(card)
    drafts = list(
        ApplicationDraft.objects.filter(user=user)
        .select_related("grant")
        .order_by("-updated_at" if sort == "recent" else "grant__deadline")
    )
    return render(
        request,
        "core/applications/list.html",
        {
            "applications": applications,
            "drafts": drafts,
            "today": timezone.localdate(),
            "columns": columns,
            "sort": sort,
            "feed": activity_feed(user),
        },
    )


@dataclass
class Step:
    label: str
    state: str  # done, current, todo or declined
    note: str


def progress(application: ApplicationCopy, history: list[StatusChange]) -> list[Step]:
    """The stages of Card detail / Applicant, from the status history. An application
    naming an administrating organisation has a sign-off stage instead of "Received by
    the funder" (the funder holds it while the organisation signs)."""
    first: dict[str, datetime] = {}
    for change in history:
        first.setdefault(change.status, change.changed_at)
    status = S(application.status)
    signing = bool(application.research_org)
    org = research_orgs.name_of(application.research_org) if signing else ""
    stage = {
        S.SUBMITTED: 1,
        S.AWAITING_SIGNATURE: 2,
        S.RO_DECLINED: 2,
        S.RO_EXPIRED: 2,
        S.RECEIVED: 2,
        S.UNDER_REVIEW: 3,
        S.NEEDS_INFO: 3,
        S.APPROVED: 4,
        S.REJECTED: 4,
    }[status]
    review_since = first.get(S.UNDER_REVIEW) or first.get(S.NEEDS_INFO)
    decided = first.get(status) if stage == 4 else None
    if signing:
        signed = status not in (S.SUBMITTED, S.AWAITING_SIGNATURE, *ENDED_BEFORE_REVIEW)
        label = f"Signed by {org}" if signed else f"Sign-off by {org}"
        second = (label, application.signed_at or first.get(status), "After you submit")
    else:
        second = ("Received by the funder", first.get(S.RECEIVED), "After you submit")
    stages = [
        ("Draft", application.draft_started_at, ""),
        ("Submitted", application.submitted_at, ""),
        second,
        (
            "In review",
            review_since,
            "After it is received" if not signing else "After it is signed",
        ),
        (
            "Approved"
            if status == S.APPROVED
            else "Declined"
            if status == S.REJECTED
            else "Decision",
            decided,
            "After the review",
        ),
    ]
    steps = []
    for index, (label, when, pending) in enumerate(stages):
        if index < stage:
            state = "done"
        elif index == stage:
            state = "declined" if status in (S.REJECTED, *ENDED_BEFORE_REVIEW) else "current"
        else:
            state = "todo"
        if status == S.AWAITING_SIGNATURE and index == stage:
            note = "Waiting for the signature"
        elif when:
            note = f"Since {when:%-d %b}" if state == "current" and index == 3 else f"{when:%-d %b}"
        else:
            note = pending
        steps.append(Step(label, state, note))
    return steps


# "What happens next" on the Activity tab, by status.
NEXT_STEPS = {
    S.SUBMITTED: "The funder confirms it has received your application.",
    S.AWAITING_SIGNATURE: (
        "Your organisation signs your application off, then the funder reviews it."
    ),
    S.RO_DECLINED: "Your organisation did not sign. You can apply again while the call is open.",
    S.RO_EXPIRED: (
        "Your organisation did not sign in time. You can apply again while the call is open."
    ),
    S.RECEIVED: "The funder sends your application to a review panel.",
    S.UNDER_REVIEW: "The panel scores your application, then the funder decides.",
    S.NEEDS_INFO: "The funder needs more information. Answer its questions under Messages.",
    S.APPROVED: "Your organisation receives the money for your project.",
    S.REJECTED: "This application is closed. Look for the next call under Open calls.",
}


def application_activity(
    application: ApplicationCopy, history: list[StatusChange], questions: list[QuestionCopy]
) -> list[Month]:
    """Card detail / Applicant, Activity tab: what happened, newest first, by month."""
    funder = application.grant.org_name
    events = [Event(application.submitted_at, "You", "submitted the application")]
    if application.draft_started_at:
        events.append(Event(application.draft_started_at, "You", "started a draft"))
    org = research_orgs.name_of(application.research_org) if application.research_org else ""
    if application.signed_at:
        events.append(Event(application.signed_at, org, "signed your application off"))
    for change in history:
        # "You submitted" is already there; with a sign-off, "signed" says it arrived.
        if change.status == S.SUBMITTED or (change.status == S.RECEIVED and application.signed_at):
            continue
        label = str(S(change.status).label)
        events.append(Event(change.changed_at, funder, f"set the status to {label}"))
    for q in questions:
        events.append(Event(q.asked_at, funder, "sent you a question", q.text))
        if q.answered_at:
            events.append(Event(q.answered_at, "You", "answered", q.answer))
    return by_month(events)


@login_required
def my_application(request: HttpRequest, public_id: str) -> HttpResponse:
    application = get_object_or_404(
        ApplicationCopy.objects.select_related("grant"), public_id=public_id, user=_user(request)
    )
    history = list(StatusChange.objects.filter(application=application))
    questions = list(QuestionCopy.objects.filter(application=application))
    steps = progress(application, history)
    return render(
        request,
        "core/applications/detail.html",
        {
            "application": application,
            "answers": labelled_answers(application.grant.form_schema, application.answers),
            "history": history,
            "questions": questions,
            "open_questions": sum(1 for q in questions if not q.answered_at),
            "steps": steps,
            "stage": next(i for i, s in enumerate(steps, 1) if s.state != "done"),
            "months": application_activity(application, history, questions),
            "next_step": NEXT_STEPS[S(application.status)],
        },
    )


@post_required
@login_required
def answer_question(request: HttpRequest, question_id: int) -> HttpResponse:
    question = get_object_or_404(QuestionCopy, pk=question_id, application__user=_user(request))
    answer = request.POST.get("answer", "").strip()
    if not answer or len(answer) > 5000:
        messages.error(request, "Write an answer of up to 5000 characters.")
    else:
        try:
            services.answer_question(question.pk, _user(request), answer)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Your answer was sent.")
    return redirect("my_application", question.application.public_id)
