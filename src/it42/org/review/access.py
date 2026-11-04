"""Who may see and write what on a review panel.

Both the staff site (fo1.it42.vr) and the reviewer site (fo1-review.it42.vr) use these
rules, so they cannot drift apart. A "seat" is a ``PanelMember`` row bound to the
logged-in user.

- Chairpersons and supporting admins see every application of the panel's grants;
  reviewers and external reviewers only the ones the FO assigned to them.
- Declarations and assessments are written by reviewing roles (chairperson, reviewer,
  external reviewer) for assigned applications, only while the matching task is open.
- Assessments are private to their author until the review is done (the assessment task
  has ended, or an FO admin ended the review early); then the whole panel (and FO
  members) can read them and nobody can change them.
- The final statement is written by a chairperson while the final-statement task is open,
  and only once the review is done; before that the form is not shown at all.
- Supporting admins read everything, write no review content, and manage the schedule.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from it42.org.applications.models import Application

from .models import Assignment, Panel, PanelMember, PanelTask

_CACHE_ATTR = "_it42_review_seats"

# Paths reachable on the reviewer site without a panel seat.
OPEN_PREFIXES = ("/saml2/", "/logout/", "/logged-out/", "/healthz", "/static/")


def seats_of(request: HttpRequest) -> list[PanelMember]:
    """The request user's panel seats, looked up once per request."""
    if not request.user.is_authenticated:
        return []
    if not hasattr(request, _CACHE_ATTR):
        seats = list(
            PanelMember.objects.filter(user_id=request.user.pk)
            .select_related("panel")
            .order_by("panel__name")
        )
        setattr(request, _CACHE_ATTR, seats)
    cached: list[PanelMember] = getattr(request, _CACHE_ATTR)
    return cached


class ReviewerGateMiddleware:
    """Every reviewer-site page needs a login and at least one panel seat.

    Logged-in users without a seat get the not-a-reviewer page and no data.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(OPEN_PREFIXES):
            return self.get_response(request)
        if not request.user.is_authenticated:
            return redirect(f"/saml2/login/?next={request.path}")
        if not seats_of(request):
            return render(request, "org/review/site/not_reviewer.html", status=403)
        return self.get_response(request)


def reviewer_context(request: HttpRequest) -> dict[str, Any]:
    return {"seats": seats_of(request), "ORG_NAME": settings.ORG_NAME}


def seat_or_404(panel: Panel, user: Any) -> PanelMember:
    seat = PanelMember.objects.filter(panel=panel, user_id=user.pk).select_related("user").first()
    if seat is None:
        raise Http404("No seat on this panel")
    seat.panel = panel
    return seat


def is_assigned(seat: PanelMember, application: Application) -> bool:
    return Assignment.objects.filter(member=seat, application=application).exists()


def visible_applications(panel: Panel, seat: PanelMember) -> Any:
    """Applications this seat may open: all of the panel's, or only the assigned ones."""
    applications = panel.applications()
    if seat.sees_all:
        return applications
    assigned = Assignment.objects.filter(member=seat).values("application_id")
    return applications.filter(pk__in=assigned)


def can_declare(seat: PanelMember, application: Application, now: datetime) -> bool:
    return (
        seat.reviews
        and is_assigned(seat, application)
        and seat.panel.task_open(PanelTask.Kind.CONFLICT, now)
    )


def can_assess(seat: PanelMember, application: Application, now: datetime) -> bool:
    return (
        seat.reviews
        and is_assigned(seat, application)
        and seat.panel.task_open(PanelTask.Kind.ASSESSMENT, now)
        and not seat.panel.review_done(now)
    )


def can_write_final(seat: PanelMember, now: datetime) -> bool:
    return (
        seat.is_chair
        and seat.panel.review_done(now)
        and seat.panel.task_open(PanelTask.Kind.FINAL, now)
    )


def can_see_declarations(seat: PanelMember) -> bool:
    """Chairpersons and supporting admins see everyone's declarations."""
    return seat.sees_all


def can_manage_schedule(seat: PanelMember) -> bool:
    return seat.is_support
