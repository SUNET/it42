from collections import defaultdict
from typing import Any

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from it42.common.agenda import Deadline, agenda
from it42.common.formschema import (
    ADMIN_ORG_FIELD,
    BASE_FIELD_NAMES,
    MAX_FIELDS,
    MAX_OPTIONS,
    OPTIONAL_BASE_FIELDS,
    WIDGETS,
)
from it42.common.http import post_required
from it42.common.statuses import ENDED_BEFORE_REVIEW, NOT_REVIEWABLE, ApplicationStatus
from it42.org.applications.models import Application, Question
from it42.org.members.access import admin_required
from it42.org.review.models import Assessment, Assignment, Meeting, PanelTask
from it42.org.review.services import grant_panels

from . import services
from .forms import GrantForm, SignatureDeadlineForm
from .models import Grant

# Grant board columns (Dashboard / Granter): grants on the left, then the applications
# by how far their review has come.
BOARD_COLUMNS = [
    ("draft", "Grant draft"),
    ("published", "Grant published"),
    ("signing", "Awaiting signature"),
    ("submissions", "Submissions"),
    ("assigned", "Reviewers assigned"),
    ("review", "Review process"),
    ("decided", "Granted / Declined"),
]


def _application_column(application: Application, assigned: int) -> str:
    if application.status in ENDED_BEFORE_REVIEW:
        return "decided"
    match application.status:
        case ApplicationStatus.AWAITING_SIGNATURE:
            return "signing"
        case ApplicationStatus.APPROVED | ApplicationStatus.REJECTED:
            return "decided"
        case ApplicationStatus.UNDER_REVIEW | ApplicationStatus.NEEDS_INFO:
            return "review"
    return "assigned" if assigned else "submissions"


def dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    sort = "deadline" if request.GET.get("sort") == "deadline" else "recent"
    grants = list(
        Grant.objects.select_related("created_by").annotate(
            application_count=Count("applications"),
            today_count=Count("applications", filter=Q(applications__received_at__date=today)),
        )
    )
    applications = list(
        Application.objects.select_related("grant").annotate(
            question_count=Count("questions", distinct=True),
            open_questions=Count("questions", filter=Q(questions__answered_at=None), distinct=True),
        )
    )
    assigned: dict[int, int] = defaultdict(int)
    for application_id in Assignment.objects.values_list("application_id", flat=True):
        assigned[application_id] += 1
    if sort == "deadline":
        grants.sort(key=lambda g: (g.deadline, g.title))
        applications.sort(key=lambda a: (a.grant.deadline, a.applicant_name))
    else:
        grants.sort(key=lambda g: g.updated_at, reverse=True)
        applications.sort(key=lambda a: a.updated_at, reverse=True)

    cards: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in BOARD_COLUMNS}
    panels = grant_panels([g.pk for g in grants if g.status != Grant.Status.DRAFT])
    for grant in grants:
        key = "draft" if grant.status == Grant.Status.DRAFT else "published"
        progress = panels.get(grant.pk, [])
        cards[key].append(
            {
                "grant": grant,
                "panels": len(progress),
                "reviewers": sum(p.reviewers for p in progress),
            }
        )
    for application in applications:
        n = assigned[application.pk]
        cards[_application_column(application, n)].append(
            {"application": application, "assigned": n}
        )
    upcoming = [g.deadline for g in grants if g.status == Grant.Status.PUBLISHED]
    next_deadline = min((d for d in upcoming if d >= today), default=None)
    return render(
        request,
        "org/dashboard.html",
        {
            "columns": [
                {"key": key, "title": title, "cards": cards[key]} for key, title in BOARD_COLUMNS
            ],
            "sort": sort,
            "next_deadline": next_deadline,
            "feed": _feed(),
            **agenda(today, org_deadlines(grants)),
        },
    )


def _feed(limit: int = 5) -> list[dict[str, Any]]:
    """Latest applications and answered questions for the Notifications panel."""
    received = [
        {
            "icon": "file-text",
            "text": f"{a.applicant_name} applied to {a.grant.title}.",
            "when": a.received_at,
            "application": a,
        }
        for a in Application.objects.select_related("grant").order_by("-received_at")[:limit]
    ]
    answered = [
        {
            "icon": "chat-circle-dots",
            "text": f"{q.application.applicant_name} answered a question.",
            "when": q.answered_at,
            "application": q.application,
        }
        for q in Question.objects.exclude(answered_at=None)
        .select_related("application")
        .order_by("-answered_at")[:limit]
    ]
    return sorted(received + answered, key=lambda n: n["when"], reverse=True)[:limit]


def org_deadlines(grants: list[Grant]) -> list[Deadline]:
    """Dated items of the org: published grants' deadlines, review task ends, meetings."""
    items = [
        Deadline("Call closes", g.title, g.deadline, "call")
        for g in grants
        if g.status == Grant.Status.PUBLISHED
    ]
    waiting = set(
        Application.objects.filter(status=ApplicationStatus.AWAITING_SIGNATURE).values_list(
            "grant_id", flat=True
        )
    )
    items += [
        Deadline("Organisation sign-off", g.title, g.signature_deadline, "signoff")
        for g in grants
        if g.status == Grant.Status.PUBLISHED or g.pk in waiting
    ]
    items += [
        Deadline(t.title, t.panel.name, timezone.localdate(t.ends_at), "task")
        for t in PanelTask.objects.select_related("panel")
    ]
    items += [
        Deadline(m.title, m.panel.name, timezone.localdate(m.starts_at), "meeting")
        for m in Meeting.objects.select_related("panel")
    ]
    return items


def builder_config() -> dict[str, Any]:
    """What the drag-and-drop builder needs: the palette and the locked base fields
    (``optional`` lists the locked fields whose Required box stays editable)."""
    return {
        "widgets": [
            {
                "type": field_type,
                "label": w["label"],
                "group": w["group"],
                "keys": list(w["keys"]),
                "palette": w.get("palette", True),
            }
            for field_type, w in WIDGETS.items()
        ],
        "locked": list(BASE_FIELD_NAMES),
        "optional": list(OPTIONAL_BASE_FIELDS),
        "type_names": {"research_org": ADMIN_ORG_FIELD},
        "max_fields": MAX_FIELDS,
        "max_options": MAX_OPTIONS,
    }


def _builder(request: HttpRequest, form: GrantForm, grant: Grant | None) -> HttpResponse:
    return render(
        request,
        "org/grants/form.html",
        {"form": form, "grant": grant, "builder_config": builder_config()},
    )


def published(request: HttpRequest) -> HttpResponse:
    """Published grants (Dashboard / Granter - Published grants): every grant that is open
    or closed, with its applications, how many passed sign-off, how many are fully
    reviewed and each review panel's progress."""
    sort = "deadline" if request.GET.get("sort") == "deadline" else "recent"
    today = timezone.localdate()
    grants = list(
        Grant.objects.exclude(status=Grant.Status.DRAFT).annotate(
            application_count=Count("applications", distinct=True),
            eligible_count=Count(
                "applications",
                filter=~Q(applications__status__in=NOT_REVIEWABLE),
                distinct=True,
            ),
            today_count=Count(
                "applications", filter=Q(applications__received_at__date=today), distinct=True
            ),
        )
    )
    if sort == "deadline":
        grants.sort(key=lambda g: (g.deadline, g.title))
    else:
        grants.sort(key=lambda g: g.updated_at, reverse=True)
    panels = grant_panels([g.pk for g in grants])
    reviewed = _reviewed_counts([g.pk for g in grants])
    cards = [
        {
            "grant": grant,
            "panels": panels[grant.pk],
            "reviewers": sum(p.reviewers for p in panels[grant.pk]),
            "reviewed": reviewed.get(grant.pk, 0),
        }
        for grant in grants
    ]
    upcoming = [g.deadline for g in grants if g.status == Grant.Status.PUBLISHED]
    return render(
        request,
        "org/grants/published.html",
        {
            "cards": cards,
            "sort": sort,
            "next_deadline": min((d for d in upcoming if d >= today), default=None),
            "totals": {
                "applications": Application.objects.filter(grant__in=grants).count(),
                "panels": len({p.panel.pk for ps in panels.values() for p in ps}),
            },
        },
    )


def _reviewed_counts(grant_ids: list[int]) -> dict[int, int]:
    """grant id -> applications whose every assigned reviewer has sent an assessment."""
    assigned: dict[int, set[int]] = defaultdict(set)
    for application_id, member_id in Assignment.objects.filter(
        application__grant_id__in=grant_ids
    ).values_list("application_id", "member_id"):
        assigned[application_id].add(member_id)
    assessed: dict[int, set[int]] = defaultdict(set)
    for application_id, member_id in Assessment.objects.filter(
        application__grant_id__in=grant_ids
    ).values_list("application_id", "member_id"):
        assessed[application_id].add(member_id)
    counts: dict[int, int] = defaultdict(int)
    grant_of = dict(Application.objects.filter(pk__in=assigned).values_list("pk", "grant_id"))
    for application_id, members in assigned.items():
        if members <= assessed[application_id]:
            counts[grant_of[application_id]] += 1
    return counts


def grant_list(request: HttpRequest) -> HttpResponse:
    grants = Grant.objects.annotate(application_count=Count("applications"))
    return render(request, "org/grants/list.html", {"grants": grants})


@admin_required
def grant_create(request: HttpRequest) -> HttpResponse:
    form = GrantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        grant = form.save(commit=False)
        grant.created_by = request.user
        grant.save()
        messages.success(request, "Draft saved. Publish it to show it on it42.vr.")
        return redirect("grant_list")
    return _builder(request, form, None)


@admin_required
def grant_edit(request: HttpRequest, grant_id: int) -> HttpResponse:
    grant = get_object_or_404(Grant, pk=grant_id)
    if grant.status != Grant.Status.DRAFT:
        messages.error(request, "Only drafts can be edited.")
        return redirect("grant_list")
    form = GrantForm(request.POST or None, instance=grant)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Draft updated.")
        return redirect("grant_list")
    return _builder(request, form, grant)


@post_required
@admin_required
def grant_publish(request: HttpRequest, grant_id: int) -> HttpResponse:
    get_object_or_404(Grant, pk=grant_id)
    try:
        grant = services.publish(grant_id)
    except services.InvalidTransition as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{grant.title}” is published.")
    return redirect("grant_list")


@post_required
@admin_required
def grant_close(request: HttpRequest, grant_id: int) -> HttpResponse:
    get_object_or_404(Grant, pk=grant_id)
    try:
        grant = services.close(grant_id)
    except services.InvalidTransition as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"“{grant.title}” is closed for new applications.")
    return redirect("grant_list")


@post_required
@admin_required
def grant_signature_deadline(request: HttpRequest, grant_id: int) -> HttpResponse:
    grant = get_object_or_404(Grant, pk=grant_id)
    form = SignatureDeadlineForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid date.")
    else:
        try:
            told = services.set_signature_deadline(
                grant.pk, form.cleaned_data["signature_deadline"]
            )
        except services.InvalidTransition as exc:
            messages.error(request, str(exc))
        else:
            note = f" {told} open request{'s' if told != 1 else ''} updated." if told else ""
            messages.success(request, f"Organisations can now sign until the new date.{note}")
    return redirect("grant_applications", grant.pk)
