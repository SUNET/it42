"""The funding organisation's work queue, shared by the board and table views."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.db.models import Count, Exists, Max, OuterRef, Prefetch, Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from it42.common.statuses import ENDED_BEFORE_REVIEW, NOT_REVIEWABLE, ApplicationStatus
from it42.org.applications.models import Application
from it42.org.review.models import Assessment, Assignment, Panel, PanelMember, PanelTask

from .models import BoardNote, Category, Grant

STAGES = {
    "draft": "Call draft",
    "todo": "Call to do",
    "waiting": "Awaiting responses",
    "panels": "Review panels",
    "decided": "Granted / Declined",
    "paused": "Paused",
    "archive": "Send to archive",
}
TABS = {
    "attention": "Attention",
    "todo": "Call to do",
    "waiting": "Awaiting responses",
    "paused": "Paused",
    "granted": "Granted",
    "all": "All",
}
DECISIONS = (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED)


@dataclass
class Card:
    """A link to one call, application or panel, with the work and date it represents."""

    key: str
    stage: str
    title: str
    badge: str
    tone: str
    subtitle: str
    url: str
    workflow: str
    calls: tuple[Grant, ...]
    updated: datetime
    date_label: str = ""
    when: date | None = None
    searchable: str = ""
    embedded: bool = True
    outcome: str = ""
    progress: tuple[int, int] | None = None
    note: str = ""
    lookup_only: bool = False
    active_panel: bool = False

    @property
    def is_call(self) -> bool:
        """Call cards support board pausing and category changes."""
        return self.key.startswith("grant:")

    @property
    def archivable(self) -> bool:
        """Only final funding decisions can move to the application archive."""
        return self.outcome in DECISIONS

    def matches_tab(self, tab: str) -> bool:
        """Attention combines the three queues the granter needs to monitor."""
        if tab == "all":
            return self.stage != "paused"
        if tab == "attention":
            return self.stage in {"todo", "waiting"} or self.active_panel
        if tab == "granted":
            return self.outcome == ApplicationStatus.APPROVED
        return self.stage == tab


def _application_card(app: Application, assigned: int, received: int, panels: list[Panel]) -> Card:
    """Surface decisions, waits, and the next staff action for a single application."""
    status = ApplicationStatus(app.status)
    label = str(status.label)
    url = reverse("application_detail", args=[app.pk])
    anchor = ""
    last_answer = getattr(app, "last_answer", None)
    answered = last_answer and last_answer >= app.updated_at
    lookup_only = False
    deadline = None
    date_label = ""
    workflow = "Application assessment"
    if status in DECISIONS:
        accepted = status == ApplicationStatus.APPROVED
        stage, badge, tone = (
            "decided",
            "Accepted" if accepted else "Declined",
            "green" if accepted else "red",
        )
        date_label = "Granted" if accepted else "Declined"
        deadline = timezone.localdate(app.decided_at) if app.decided_at else None
        workflow = "Funding decision"
    elif status in ENDED_BEFORE_REVIEW:
        stage, badge, tone = "decided", label, "grey"
        workflow = "Organisation sign-off"
        if app.signed_at:
            deadline, date_label = timezone.localdate(app.signed_at), "Sign-off declined"
        elif status == ApplicationStatus.RO_EXPIRED:
            deadline, date_label = app.grant.signature_deadline, "Sign-off expired"
    elif status == ApplicationStatus.AWAITING_SIGNATURE:
        stage, badge, tone = "waiting", "Waiting for sign-off", "lavender"
        workflow, deadline, date_label = (
            "Organisation sign-off",
            app.grant.signature_deadline,
            "Sign by",
        )
    elif getattr(app, "outstanding", 0) or (
        status == ApplicationStatus.NEEDS_INFO and not answered
    ):
        stage, badge, tone = "waiting", "Waiting for applicant", "lavender"
        workflow, anchor = "Applicant correspondence", "#questions"
    elif answered:
        stage, badge, tone = "todo", "Review applicant response", "peach"
        workflow, anchor = "Applicant correspondence", "#questions"
    elif not assigned:
        stage, badge, tone = "todo", "Review application", "peach"
        if panels:
            badge = "Assign reviewers"
            if len(panels) == 1:
                url = reverse("panel_application", args=[panels[0].pk, app.pk])
            else:
                # Staff choose the appropriate panel from the application's Reviews tab.
                anchor = "#reviews"
    elif received == assigned:
        stage, badge, tone = "todo", "Reviews received", "peach"
        workflow, anchor = "Funding decision", "#reviews"
    else:
        # On the unfiltered board the panel represents work already in reviewers' hands.
        stage, badge, tone = "panels", "With reviewers", "peach"
        workflow, lookup_only = "Panel review", True
    return Card(
        key=f"application:{app.pk}",
        stage=stage,
        badge=badge,
        tone=tone,
        title=app.answers.get("project_title") or app.applicant_name,
        subtitle=f"{app.grant.title} · {app.applicant_name}",
        calls=(app.grant,),
        workflow=workflow,
        url=url + anchor,
        lookup_only=lookup_only,
        updated=max(app.updated_at, last_answer) if last_answer else app.updated_at,
        when=deadline,
        date_label=date_label,
        outcome=status if status in DECISIONS else "",
        searchable=f"{app.public_id} {app.applicant_name} {app.grant.title}",
    )


def _call_card(grant: Grant, panels: list[Panel], admin: bool) -> Card | None:
    """Calls enter the work queue when a draft or panel setup needs attention."""
    url = reverse("grant_applications", args=[grant.pk])
    embedded = True
    subtitle = f"Grant call · {grant.category}" if grant.category else "Grant call"
    date_label = "Closed" if grant.status == Grant.Status.CLOSED else "Closes"
    if grant.board_paused:
        stage, badge, tone = "paused", "Paused", "grey"
    elif grant.status == Grant.Status.DRAFT:
        stage, badge, tone = "draft", "Unpublished", "grey"
    else:
        if not panels and (
            grant.status == Grant.Status.PUBLISHED or getattr(grant, "eligible_count", 0)
        ):
            action = "Set up review panel"
            url, embedded = reverse("call_panels", args=[grant.pk]), False
        elif panel := next((p for p in panels if not getattr(p, "reviewers", 0)), None):
            action = "Panel needs reviewers"
            url = reverse("panel_detail", args=[panel.pk]) + "#seats"
        else:
            return None
        stage, badge, tone = "todo", "Needs action", "peach"
        count = getattr(grant, "application_count", 0)
        subtitle = f"{action} · {count} application{'s' if count != 1 else ''}"
    if grant.status == Grant.Status.DRAFT:
        date_label = "Due"
        if admin:
            url = reverse("grant_edit", args=[grant.pk])
    return Card(
        key=f"grant:{grant.pk}",
        stage=stage,
        badge=badge,
        tone=tone,
        title=grant.title,
        subtitle=subtitle,
        calls=(grant,),
        workflow="Call preparation" if grant.status == Grant.Status.DRAFT else "Panel setup",
        url=url,
        embedded=embedded,
        updated=grant.updated_at,
        date_label=date_label,
        when=grant.deadline,
    )


def build_cards(grants: list[Grant], admin: bool, now: datetime) -> list[Card]:
    """Build the queues in batches. Count only assessments of current assignments."""
    cards: list[Card] = []
    grant_map = {g.pk: g for g in grants}
    panels_by_grant: dict[int, list[Panel]] = defaultdict(list)
    assignments = (
        Assignment.objects.annotate(
            submitted=Exists(
                Assessment.objects.filter(
                    member_id=OuterRef("member_id"), application_id=OuterRef("application_id")
                )
            ),
        )
        .order_by()
        .values_list("member__panel_id", "application_id", "submitted")
    )
    assigned_by_app: Counter[int] = Counter()
    received_by_app: Counter[int] = Counter()
    assigned_by_panel: Counter[int] = Counter()
    received_by_panel: Counter[int] = Counter()
    for panel_id, app_id, submitted in assignments:
        assigned_by_panel[panel_id] += 1
        assigned_by_app[app_id] += 1
        if submitted:
            received_by_panel[panel_id] += 1
            received_by_app[app_id] += 1

    panels = Panel.objects.prefetch_related(
        Prefetch("grants", queryset=Grant.objects.only("pk")),
        Prefetch("tasks", to_attr="board_tasks"),
        Prefetch("meetings", to_attr="board_meetings"),
    ).annotate(reviewers=Count("members", filter=Q(members__role__in=PanelMember.REVIEWING_ROLES)))
    for panel in panels:
        calls = tuple(grant_map[g.pk] for g in panel.grants.all() if g.pk in grant_map)
        for grant in calls:
            panels_by_grant[grant.pk].append(panel)
        tasks = getattr(panel, "board_tasks", [])
        dates = [
            (t.ends_at, t.title)
            for t in tasks
            if t.ends_at >= now
            and not (panel.review_closed_at and t.kind == PanelTask.Kind.ASSESSMENT)
        ]
        dates.extend(
            (m.starts_at, m.title)
            for m in getattr(panel, "board_meetings", [])
            if m.starts_at >= now
        )
        upcoming = min(dates, default=None)
        reviewers = getattr(panel, "reviewers", 0)
        done = bool(panel.review_closed_at and panel.review_closed_at <= now) or any(
            t.kind == PanelTask.Kind.ASSESSMENT and t.ends_at <= now for t in tasks
        )
        badge = "Review complete" if done else "In review" if reviewers else "Needs reviewers"
        count = sum(getattr(g, "eligible_count", 0) for g in calls)
        call_names = ", ".join(g.title for g in calls) or "No call attached"
        cards.append(
            Card(
                key=f"panel:{panel.pk}",
                stage="panels",
                title=panel.name,
                badge=badge,
                tone="peach",
                subtitle=(
                    f"{call_names} · {count} application{'s' if count != 1 else ''}"
                    f" · {reviewers} reviewer{'s' if reviewers != 1 else ''}"
                ),
                active_panel=not done or upcoming is not None,
                calls=calls,
                workflow="Panel review",
                updated=panel.updated_at,
                url=reverse("panel_detail", args=[panel.pk]),
                progress=(received_by_panel[panel.pk], assigned_by_panel[panel.pk]),
                date_label=upcoming[1] if upcoming else "",
                when=timezone.localdate(upcoming[0]) if upcoming else None,
            )
        )
    for grant in grants:
        if card := _call_card(grant, panels_by_grant[grant.pk], admin):
            cards.append(card)
    applications = Application.objects.exclude(archive_at__lte=now).annotate(
        outstanding=Count("questions", filter=Q(questions__answered_at__isnull=True)),
        last_answer=Max("questions__answered_at"),
    )
    for app in applications.only(
        "grant_id",
        "status",
        "answers",
        "applicant_name",
        "public_id",
        "signed_at",
        "decided_at",
        "updated_at",
    ):
        # Use the same call snapshot in both queues; newly arrived calls appear on refresh.
        if app.grant_id not in grant_map:
            continue
        app.grant = grant_map[app.grant_id]
        cards.append(
            _application_card(
                app, assigned_by_app[app.pk], received_by_app[app.pk], panels_by_grant[app.grant_id]
            )
        )
    return cards


def board_context(request: HttpRequest, admin: bool) -> tuple[list[Grant], dict[str, Any]]:
    """Apply the same search, filters and grouping to both presentations."""
    grants = list(
        Grant.objects.select_related("category")
        .defer("form_schema", "description")
        .annotate(
            application_count=Count("applications"),
            eligible_count=Count(
                "applications", filter=~Q(applications__status__in=NOT_REVIEWABLE)
            ),
        )
    )
    cards = build_cards(grants, admin, timezone.now())
    notes = {}
    for grant, app, panel, text in BoardNote.objects.filter(owner_id=request.user.pk).values_list(
        "grant_id", "application_id", "panel_id", "text"
    ):
        key = f"grant:{grant}" if grant else f"application:{app}" if app else f"panel:{panel}"
        notes[key] = text
    query = request.GET.get("q", "").strip()
    q = query.casefold()
    status = request.GET.get("status", "")
    tag = request.GET.get("tag", "")
    noted = request.GET.get("notes") == "mine"
    for card in cards:
        card.note = notes.get(card.key, "")
    statuses = sorted({c.badge for c in cards})
    tags = {str(pk): name for pk, name in Category.objects.values_list("pk", "name")}
    filtered = [
        c
        for c in cards
        if (not c.lookup_only or q or noted or status == c.badge)
        and (not q or q in f"{c.title} {c.subtitle} {c.searchable}".casefold())
        and (not status or status == c.badge)
        and (not tag or any(g.category and str(g.category.pk) == tag for g in c.calls))
        and (not noted or c.note)
    ]
    tab = request.GET.get("tab", "all")
    if tab not in TABS:
        tab = "all"
    tabs = [(key, label, sum(c.matches_tab(key) for c in filtered)) for key, label in TABS.items()]
    shown = [c for c in filtered if c.matches_tab(tab)]
    sort = request.GET.get("sort", "recent")
    if sort == "deadline":
        shown.sort(key=lambda c: (c.when or date.max, c.title.casefold(), c.key))
    elif sort == "title":
        shown.sort(key=lambda c: (c.title.casefold(), c.key))
    else:
        sort = "recent"
        shown.sort(key=lambda c: (c.updated, c.key), reverse=True)

    if tab in ("all", "attention"):
        stages = [key for key in STAGES if key != "paused"]
    else:
        stages = ["decided" if tab == "granted" else tab]
    grouping = request.GET.get("group", "all")
    groups: dict[str, list[Card]] = defaultdict(list)
    if grouping == "call":
        for card in shown:
            for call in card.calls:
                groups[f"{call.title} (#{call.pk})"].append(card)
            if not card.calls:
                groups["No call attached"].append(card)
    elif grouping == "workflow":
        for card in shown:
            groups[card.workflow].append(card)
    else:
        grouping = "all"
    if not groups:
        groups[""] = shown
    sections = []
    for name, items in sorted(groups.items()):
        columns = [
            {"key": k, "title": STAGES[k], "cards": [c for c in items if c.stage == k]}
            for k in stages
        ]
        sections.append({"name": name, "columns": columns, "cards": items})
    return grants, {
        "selecting": request.GET.get("select") == "1",
        "tag_name": tags.get(tag, ""),
        "sections": sections,
        "tabs": tabs,
        "tab": tab,
        "sort": sort,
        "grouping": grouping,
        "query": query,
        "status": status,
        "tag": tag,
        "noted": noted,
        "statuses": statuses,
        "tags": sorted(tags.items(), key=lambda item: item[1].casefold()),
        "table": request.GET.get("view") == "table",
        "stats": [
            (name, sum(c.stage == key for c in filtered))
            for key, name in STAGES.items()
            if key != "archive"
        ],
    }
