"""What the staff application page shows besides the application itself (Card detail /
Application from granter view: Grant details, Reviews and Activity tabs).

Everything is built from rows the org already keeps; there is no separate event log.
Assessment contents (grades) appear only once their panel's review is done, as on the
review pages (review/access.py).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.utils import timezone

from it42.common import research_orgs
from it42.common.activity import Event, Month, by_month
from it42.common.formschema import is_layout
from it42.org.review.models import Assessment, Assignment, Meeting, Panel, PanelTask
from it42.org.review.services import ApplicationReview

from .models import Application, Question, ReviewNote


def activity(application: Application, reviews: list[ApplicationReview]) -> list[Month]:
    """Everything that happened to the application, newest first, grouped by month."""
    org = research_orgs.name_of(application.research_org) if application.research_org else ""
    events = [
        Event(application.submitted_at, application.applicant_name, "submitted the application"),
        Event(application.received_at, "IT42", "delivered the application to this site"),
    ]
    if application.signed_at:
        declined = application.status == "ro_declined"
        events.append(
            Event(
                application.signed_at,
                org or application.signed_by,
                "declined the application" if declined else "signed the application off",
                application.signature_note,
            )
        )
    for a in Assignment.objects.filter(application=application).select_related(
        "member", "member__user", "member__panel"
    ):
        events.append(
            Event(a.assigned_at, a.member.display_name, f"was assigned ({a.member.panel})")
        )
    shared = {r.panel.pk for r in reviews if r.shared}
    for s in Assessment.objects.filter(application=application).select_related(
        "member", "member__user"
    ):
        grade = f"Grade {s.preliminary_grade}/10" if s.member.panel_id in shared else ""
        events.append(Event(s.created_at, s.member.display_name, "sent an assessment", grade))
    for r in reviews:
        if r.final is not None:
            events.append(
                Event(
                    r.final.created_at,
                    r.final.author.display_name if r.final.author else r.panel.name,
                    "wrote the final statement",
                    f"Grade {r.final.final_grade}/10",
                )
            )
    for q in Question.objects.filter(application=application).select_related("asked_by"):
        events.append(Event(q.asked_at, str(q.asked_by), "asked the applicant a question", q.text))
        if q.answered_at:
            events.append(Event(q.answered_at, application.applicant_name, "answered", q.answer))
    for n in ReviewNote.objects.filter(application=application).select_related("author"):
        events.append(Event(n.created_at, str(n.author), "added an internal note", n.text, True))
    return by_month(events)


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    tone: str


def people(application: Application, reviews: list[ApplicationReview]) -> list[Person]:
    found = [Person(application.applicant_name, "Applicant", "applicant")]
    if application.research_org:
        found.append(
            Person(research_orgs.name_of(application.research_org), "Organization", "organization")
        )
    seen: set[str] = set()
    for review in reviews:
        for member in review.assigned:
            if member.email not in seen:
                seen.add(member.email)
                found.append(Person(member.display_name, member.role_label, "reviewer"))
    found.append(Person("Granter team", "Granter", "granter"))
    return found


@dataclass(frozen=True)
class KeyDate:
    day: date
    text: str
    current: bool = False


def key_dates(application: Application) -> list[KeyDate]:
    """The call's dates and the review schedule of every panel handling the grant."""
    grant = application.grant
    today = timezone.localdate()
    dates = [
        KeyDate(grant.created_at.date(), "Call created"),
        KeyDate(grant.deadline, "Applications close"),
        KeyDate(grant.signature_deadline, "Organisations sign off by"),
    ]
    panels = Panel.objects.filter(grants=grant)
    for task in PanelTask.objects.filter(panel__in=panels).select_related("panel"):
        start, end = timezone.localdate(task.starts_at), timezone.localdate(task.ends_at)
        dates.append(KeyDate(end, f"Last day: {task.title} ({task.panel})", start <= today <= end))
    for meeting in Meeting.objects.filter(panel__in=panels).select_related("panel"):
        dates.append(
            KeyDate(timezone.localdate(meeting.starts_at), f"{meeting.title} ({meeting.panel})")
        )
    dates.sort(key=lambda d: d.day)
    return dates


def form_sections(schema: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """(heading, number of fields) per section of the application form."""
    sections: list[tuple[str, int]] = [("Applicant", 0)]
    for spec in schema:
        if spec.get("type") == "heading":
            sections.append((str(spec.get("label", "")), 0))
        elif not is_layout(spec):
            title, count = sections[-1]
            sections[-1] = (title, count + 1)
    return [s for s in sections if s[1]]


@dataclass(frozen=True)
class ReviewSummary:
    assigned: int
    submitted: int
    average: float | None
    final_grade: int | None


def review_summary(application: Application, reviews: list[ApplicationReview]) -> ReviewSummary:
    shared = [a.preliminary_grade for r in reviews if r.shared for a in r.assessments]
    submitted = Assessment.objects.filter(application=application).count()
    finals = [r.final.final_grade for r in reviews if r.final is not None]
    return ReviewSummary(
        assigned=sum(len(r.assigned) for r in reviews),
        submitted=submitted,
        average=sum(shared) / len(shared) if shared and len(shared) == submitted else None,
        final_grade=finals[0] if len(finals) == 1 else None,
    )
