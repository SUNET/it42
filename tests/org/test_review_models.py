"""Panel models: windows, constraints, seat binding."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.db import IntegrityError
from django.utils import timezone

from it42.org.review import access, services
from it42.org.review.models import Assessment, PanelMember, PanelTask
from it42.org.review.signals import bind_seats


def test_only_one_task_of_each_special_kind(make_panel: Callable[..., Any], make_task: Any) -> None:
    panel = make_panel()
    make_task(panel, PanelTask.Kind.ASSESSMENT)
    make_task(panel, PanelTask.Kind.OTHER, title="Kick-off")
    make_task(panel, PanelTask.Kind.OTHER, title="Wrap-up")  # several "other" tasks are fine
    with pytest.raises(IntegrityError):
        make_task(panel, PanelTask.Kind.ASSESSMENT)


def test_task_window_must_be_ordered(make_panel: Callable[..., Any]) -> None:
    now = timezone.now()
    with pytest.raises(IntegrityError):
        PanelTask.objects.create(
            panel=make_panel(), kind="other", title="x", starts_at=now, ends_at=now
        )


def test_task_states(make_panel: Callable[..., Any], make_task: Any) -> None:
    panel = make_panel()
    now = timezone.now()
    assert make_task(panel, "other", open_=False).state(now) == "upcoming"
    open_task = make_task(panel, PanelTask.Kind.ASSESSMENT)
    assert open_task.state(now) == "open" and open_task.is_open(now)
    ended = make_task(panel, PanelTask.Kind.FINAL, ended=True)
    assert ended.state(now) == "ended" and ended.has_ended(now) and not ended.is_open(now)
    assert panel.task_open(PanelTask.Kind.ASSESSMENT, now)
    assert not panel.task_open(PanelTask.Kind.FINAL, now)
    assert not panel.task_open(PanelTask.Kind.CONFLICT, now)  # no such task


def test_assessments_shared_only_after_the_assessment_task_ends(
    make_panel: Callable[..., Any], make_task: Any
) -> None:
    panel = make_panel()
    now = timezone.now()
    assert not panel.assessments_shared(now)  # no task: never shared
    task = make_task(panel, PanelTask.Kind.ASSESSMENT)
    assert not panel.assessments_shared(now)
    task.ends_at = now - timedelta(minutes=1)
    task.save()
    assert panel.assessments_shared(now)


def test_seat_email_is_lower_cased_and_unique_per_panel(
    make_panel: Callable[..., Any], make_seat: Any
) -> None:
    panel = make_panel()
    seat = make_seat(panel, "Ingrid.Nystrom@UMU.se", user=False)
    assert seat.email == "ingrid.nystrom@umu.se" and seat.user_id is None
    with pytest.raises(IntegrityError):
        make_seat(panel, "ingrid.nystrom@umu.se", user=False)


def test_same_email_may_sit_on_two_panels(make_panel: Callable[..., Any], make_seat: Any) -> None:
    make_seat(make_panel("A"), "r1@example.org", user=False)
    make_seat(make_panel("B"), "r1@example.org", user=False)
    assert PanelMember.objects.filter(email="r1@example.org").count() == 2


def test_login_binds_every_unbound_seat_with_that_email(
    make_panel: Callable[..., Any], make_seat: Any, make_user: Callable[..., Any]
) -> None:
    a = make_seat(make_panel("A"), "r1@example.org", user=False)
    b = make_seat(make_panel("B"), "R1@Example.org", user=False)
    other = make_seat(make_panel("C"), "r2@example.org", user=False)
    user = make_user("r1", email="R1@example.ORG")
    bind_seats(None, None, user)
    a.refresh_from_db(), b.refresh_from_db(), other.refresh_from_db()
    assert a.user_id == user.pk and b.user_id == user.pk and other.user_id is None
    bind_seats(None, None, user)  # idempotent
    bind_seats(None, None, make_user("noemail"))  # no email: nothing happens
    assert PanelMember.objects.filter(user=user).count() == 2


def test_adding_a_seat_binds_a_user_who_already_logged_in(
    make_panel: Callable[..., Any], make_user: Callable[..., Any]
) -> None:
    user = make_user("r1", email="r1@example.org")
    seat = services.add_seat(make_panel(), " R1@example.org ", PanelMember.Role.CHAIR)
    assert seat.email == "r1@example.org" and seat.user_id == user.pk


def test_visible_applications_depend_on_the_role(
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
) -> None:
    grant = make_grant()
    other_grant = make_grant("g2")
    panel = make_panel("A", grant)
    app1, app2 = make_application(grant), make_application(grant, name="Second")
    foreign = make_application(other_grant, name="Foreign")
    chair = make_seat(panel, "chair@example.org", PanelMember.Role.CHAIR)
    support = make_seat(panel, "support@example.org", PanelMember.Role.SUPPORT)
    reviewer = make_seat(panel, "rev@example.org")
    external = make_seat(panel, "ext@example.org", PanelMember.Role.EXTERNAL)
    assign(reviewer, app1)
    assign(external, app2)
    assert set(access.visible_applications(panel, chair)) == {app1, app2}
    assert set(access.visible_applications(panel, support)) == {app1, app2}
    assert list(access.visible_applications(panel, reviewer)) == [app1]
    assert list(access.visible_applications(panel, external)) == [app2]
    assert foreign not in access.visible_applications(panel, chair)


def test_set_assignments_replaces_the_set_and_ignores_foreign_seats(
    make_panel: Callable[..., Any], make_grant: Any, make_application: Any, make_seat: Any
) -> None:
    grant = make_grant()
    panel = make_panel("A", grant)
    other_panel = make_panel("B", grant)
    app = make_application(grant)
    r1 = make_seat(panel, "r1@example.org")
    r2 = make_seat(panel, "r2@example.org")
    support = make_seat(panel, "s@example.org", PanelMember.Role.SUPPORT)
    foreign = make_seat(other_panel, "f@example.org")
    assert services.set_assignments(panel, app, {r1.pk, r2.pk, support.pk, foreign.pk}) == 2
    assert services.set_assignments(panel, app, {r2.pk}) == 1
    assert [a.application_id for a in r2.assignments.all()] == [app.pk]
    assert not r1.assignments.exists() and not foreign.assignments.exists()


def test_unlinking_a_grant_drops_its_assignments(
    make_panel: Callable[..., Any],
    make_grant: Any,
    make_application: Any,
    make_seat: Any,
    assign: Any,
) -> None:
    g1, g2 = make_grant("g1"), make_grant("g2")
    panel = make_panel("A", g1, g2)
    seat = make_seat(panel, "r1@example.org")
    assign(seat, make_application(g1))
    kept = assign(seat, make_application(g2))
    services.unlink_grant(panel, g1.pk)
    assert list(panel.grants.all()) == [g2]
    assert list(seat.assignments.all()) == [kept]


def test_grade_above_ten_is_rejected(
    make_panel: Callable[..., Any], make_grant: Any, make_application: Any, make_seat: Any
) -> None:
    grant = make_grant()
    seat = make_seat(make_panel("A", grant), "r1@example.org")
    with pytest.raises(IntegrityError):
        Assessment.objects.create(
            member=seat,
            application=make_application(grant),
            assessment="x",
            preliminary_statement="y",
            preliminary_grade=11,
        )
