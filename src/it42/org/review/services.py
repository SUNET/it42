"""Panel operations shared by the staff and reviewer sites."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from it42.org.applications.models import Application

from .models import (
    Assessment,
    Assignment,
    Declaration,
    FinalStatement,
    Panel,
    PanelMember,
    PanelTask,
)

User = get_user_model()


def add_seat(panel: Panel, email: str, role: str) -> PanelMember:
    """Create a seat; bind it at once if that email has already logged in."""
    email = email.strip().lower()
    user = User.objects.filter(email__iexact=email).exclude(sso_subject=None).first()
    return PanelMember.objects.create(panel=panel, email=email, role=role, user=user)


def set_assignments(panel: Panel, application: Application, seat_ids: set[int]) -> int:
    """Replace the set of seats assigned to an application. Returns the new count.

    Seats of other panels and non-reviewing roles are ignored.
    """
    valid = set(
        PanelMember.objects.filter(
            panel=panel, pk__in=seat_ids, role__in=PanelMember.REVIEWING_ROLES
        ).values_list("pk", flat=True)
    )
    with transaction.atomic():
        current = Assignment.objects.filter(application=application, member__panel=panel)
        current.exclude(member_id__in=valid).delete()
        existing = set(current.values_list("member_id", flat=True))
        Assignment.objects.bulk_create(
            [Assignment(member_id=pk, application=application) for pk in valid - existing]
        )
    return len(valid)


def unlink_grant(panel: Panel, grant_id: int) -> None:
    """Remove a grant from the panel together with the assignments for its applications."""
    with transaction.atomic():
        panel.grants.remove(grant_id)
        Assignment.objects.filter(member__panel=panel, application__grant_id=grant_id).delete()


@dataclass(frozen=True)
class ApplicationReview:
    """What a panel has produced about one application, for read-only display."""

    panel: Panel
    assigned: list[PanelMember]
    declarations: list[Declaration]
    shared: bool
    assessment_task: PanelTask | None
    assessments: list[Assessment]
    final: FinalStatement | None


def application_review(panel: Panel, application: Application, now: datetime) -> ApplicationReview:
    shared = panel.assessments_shared(now)
    return ApplicationReview(
        panel=panel,
        assigned=[
            a.member
            for a in Assignment.objects.filter(application=application, member__panel=panel)
            .select_related("member", "member__user")
            .order_by("member__email")
        ],
        declarations=list(
            Declaration.objects.filter(application=application, member__panel=panel)
            .select_related("member", "member__user")
            .order_by("member__email")
        ),
        shared=shared,
        assessment_task=panel.task(PanelTask.Kind.ASSESSMENT),
        assessments=list(
            Assessment.objects.filter(application=application, member__panel=panel).select_related(
                "member", "member__user"
            )
        )
        if shared
        else [],
        final=FinalStatement.objects.filter(panel=panel, application=application)
        .select_related("author")
        .first(),
    )


def panels_for_application(application: Application, now: datetime) -> list[ApplicationReview]:
    """Every panel that handles the application's grant, with what it produced so far."""
    panels = Panel.objects.filter(grants=application.grant_id).order_by("name")
    return [application_review(panel, application, now) for panel in panels]


def assignment_counts(panel: Panel) -> dict[int, int]:
    """application id -> number of assigned seats, for the panel's application list."""
    counts: dict[int, int] = {}
    for application_id in Assignment.objects.filter(member__panel=panel).values_list(
        "application_id", flat=True
    ):
        counts[application_id] = counts.get(application_id, 0) + 1
    return counts


def seat_states(seat: PanelMember, applications: list[Application]) -> dict[int, dict[str, Any]]:
    """application id -> whether this seat has declared / assessed it."""
    ids = [a.pk for a in applications]
    declared = set(
        Declaration.objects.filter(member=seat, application_id__in=ids).values_list(
            "application_id", flat=True
        )
    )
    assessed = set(
        Assessment.objects.filter(member=seat, application_id__in=ids).values_list(
            "application_id", flat=True
        )
    )
    assigned = set(
        Assignment.objects.filter(member=seat, application_id__in=ids).values_list(
            "application_id", flat=True
        )
    )
    return {
        pk: {"declared": pk in declared, "assessed": pk in assessed, "assigned": pk in assigned}
        for pk in ids
    }


@dataclass(frozen=True)
class ScoreSummary:
    """Review progress of one application for the staff site's lists.

    ``average`` covers only assessments of panels whose review is done (until then they
    are private to their authors, see access.py), so it is None while any are hidden.
    """

    assigned: int
    submitted: int
    average: float | None

    @property
    def percent(self) -> int:
        """The average as a share of the 10-point scale, for score bars."""
        return round(self.average * 10) if self.average is not None else 0


def score_summaries(applications: list[Application], now: datetime) -> dict[int, ScoreSummary]:
    """application id -> ScoreSummary, with a fixed number of queries."""
    ids = [a.pk for a in applications]
    assigned: dict[int, int] = {}
    for application_id in Assignment.objects.filter(application_id__in=ids).values_list(
        "application_id", flat=True
    ):
        assigned[application_id] = assigned.get(application_id, 0) + 1
    panels = Panel.objects.filter(grants__in={a.grant_id for a in applications}).distinct()
    shared = {panel.pk for panel in panels if panel.assessments_shared(now)}
    submitted: dict[int, int] = {}
    grades: dict[int, list[int]] = {}
    for application_id, panel_id, grade in Assessment.objects.filter(
        application_id__in=ids
    ).values_list("application_id", "member__panel_id", "preliminary_grade"):
        submitted[application_id] = submitted.get(application_id, 0) + 1
        if panel_id in shared:
            grades.setdefault(application_id, []).append(grade)
    return {
        pk: ScoreSummary(
            assigned=assigned.get(pk, 0),
            submitted=submitted.get(pk, 0),
            average=(
                sum(grades[pk]) / len(grades[pk])
                if pk in grades and len(grades[pk]) == submitted.get(pk, 0)
                else None
            ),
        )
        for pk in ids
    }


@dataclass(frozen=True)
class PanelProgress:
    """How far one panel has come with a grant's applications."""

    panel: Panel
    reviewers: int
    assigned: int
    submitted: int

    @property
    def percent(self) -> int:
        return round(100 * self.submitted / self.assigned) if self.assigned else 0


def grant_panels(grant_ids: list[int]) -> dict[int, list[PanelProgress]]:
    """grant id -> progress of every panel that handles it (assessments in / assigned)."""
    result: dict[int, list[PanelProgress]] = {pk: [] for pk in grant_ids}
    links = Panel.grants.through.objects.filter(grant_id__in=grant_ids).select_related("panel")
    for link in links.order_by("panel__name"):
        panel, grant_id = link.panel, link.grant_id
        result[grant_id].append(
            PanelProgress(
                panel=panel,
                reviewers=PanelMember.objects.filter(
                    panel=panel, role__in=PanelMember.REVIEWING_ROLES
                ).count(),
                assigned=Assignment.objects.filter(
                    member__panel=panel, application__grant_id=grant_id
                ).count(),
                submitted=Assessment.objects.filter(
                    member__panel=panel, application__grant_id=grant_id
                ).count(),
            )
        )
    return result
