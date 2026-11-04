import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.org.accounts.models import User
from it42.org.applications.models import Application
from it42.org.grants.models import Grant
from it42.org.members.models import Membership
from it42.org.review.models import Assignment, Panel, PanelMember, PanelTask


@pytest.fixture
def make_user(db: None) -> Callable[..., Any]:
    def make(subject: str, **extra: Any) -> Any:
        return User.objects.create_user(username=subject, sso_subject=subject, **extra)

    return make


@pytest.fixture
def make_member(make_user: Callable[..., Any]) -> Callable[..., Any]:
    def make(subject: str, role: str = Membership.Role.STAFF) -> Any:
        user = make_user(subject)
        Membership.objects.create(user=user, role=role, approved_at=timezone.now())
        return user

    return make


@pytest.fixture
def admin_client(make_member: Callable[..., Any]) -> Client:
    client = Client()
    client.force_login(make_member("staff1", Membership.Role.ADMIN))
    return client


@pytest.fixture
def member_client(make_member: Callable[..., Any]) -> Client:
    client = Client()
    client.force_login(make_member("staff9"))
    return client


# ---- Review panels --------------------------------------------------------------------


def _creator(make_user: Callable[..., Any]) -> Any:
    return User.objects.filter(sso_subject="creator").first() or make_user("creator")


@pytest.fixture
def make_grant(make_user: Callable[..., Any]) -> Callable[..., Grant]:
    def make(title: str = "g1", status: str = Grant.Status.PUBLISHED) -> Grant:
        return Grant.objects.create(
            title=title,
            description="d",
            deadline=timezone.localdate() + timedelta(days=30),
            form_schema=[
                {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
                {"name": "summary", "label": "Summary", "type": "textarea", "required": True},
            ],
            status=status,
            created_by=_creator(make_user),
        )

    return make


@pytest.fixture
def make_application(make_grant: Callable[..., Grant]) -> Callable[..., Application]:
    def make(grant: Grant | None = None, name: str = "Oskar Bergström") -> Application:
        return Application.objects.create(
            public_id=uuid.uuid4(),
            grant=grant or make_grant(),
            applicant_subject="a2",
            applicant_name=name,
            applicant_email="oskar.bergstrom@kth.se",
            answers={"applicant_name": name, "summary": "Measure energy use."},
            submitted_at=timezone.now(),
            seq=1,
        )

    return make


@pytest.fixture
def make_panel(make_user: Callable[..., Any]) -> Callable[..., Panel]:
    def make(name: str = "Panel A", *grants: Grant) -> Panel:
        panel = Panel.objects.create(name=name, created_by=_creator(make_user))
        panel.grants.add(*grants)
        return panel

    return make


@pytest.fixture
def make_seat(make_user: Callable[..., Any]) -> Callable[..., PanelMember]:
    """A seat bound to a user (subject = local part of the email) unless user=False."""

    def make(
        panel: Panel,
        email: str,
        role: str = PanelMember.Role.REVIEWER,
        user: Any = None,
    ) -> PanelMember:
        if user is None:
            subject = email.split("@")[0].lower()
            user = User.objects.filter(sso_subject=subject).first() or make_user(
                subject, email=email.lower()
            )
        return PanelMember.objects.create(panel=panel, email=email, role=role, user=user or None)

    return make


@pytest.fixture
def make_task(db: None) -> Callable[..., PanelTask]:
    def make(
        panel: Panel, kind: str, *, open_: bool = True, ended: bool = False, title: str = ""
    ) -> PanelTask:
        now = timezone.now()
        if ended:
            starts, ends = now - timedelta(days=2), now - timedelta(hours=1)
        elif open_:
            starts, ends = now - timedelta(hours=1), now + timedelta(days=1)
        else:
            starts, ends = now + timedelta(days=1), now + timedelta(days=2)
        return PanelTask.objects.create(
            panel=panel, kind=kind, title=title or kind, starts_at=starts, ends_at=ends
        )

    return make


@pytest.fixture
def assign(db: None) -> Callable[[PanelMember, Application], Assignment]:
    def make(seat: PanelMember, application: Application) -> Assignment:
        return Assignment.objects.create(member=seat, application=application)

    return make


@pytest.fixture
def review_site(settings: Any) -> None:
    """Serve the reviewer site (fo1-review) for one test: URLconf, gate and theme."""
    from it42.settings.base import templates

    settings.SITE_ROLE = "review"
    settings.SITE_NAME = "Org 1 review panels"
    settings.ORG_NAME = "Org 1"
    settings.THEME_COLOR = "#ffe680"
    settings.ROOT_URLCONF = "it42.org.review.site_urls"
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "MembershipGate" not in m] + [
        "it42.org.review.access.ReviewerGateMiddleware"
    ]
    settings.TEMPLATES = templates(
        [
            "it42.org.members.access.membership_context",
            "it42.org.review.access.reviewer_context",
        ]
    )


@pytest.fixture
def seat_client(review_site: None) -> Callable[[PanelMember], Client]:
    """A client logged in (on the reviewer site) as the user bound to a seat."""

    def make(seat: PanelMember) -> Client:
        client = Client()
        client.force_login(seat.user)
        return client

    return make
