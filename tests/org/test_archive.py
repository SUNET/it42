from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.models import OutboxEvent
from it42.org.applications.models import Application
from it42.org.applications.services import archive_time


@pytest.mark.parametrize("outcome", ["approved", "rejected"])
def test_decision_moves_from_board_to_archive(
    make_application: Callable[..., Application],
    member_client: Client,
    admin_client: Client,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    application = make_application()
    detail = f"/applications/{application.pk}/"
    when = datetime(2024, 1, 31, 9, 30, tzinfo=UTC)
    due = datetime(2024, 2, 29, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: when)
    member_client.post(detail + "status/", {"status": outcome})
    application.refresh_from_db()
    assert str(application.decided_by) == "staff9"
    assert application.decided_at == when
    assert application.archive_at == due

    def board_ids() -> list[int]:
        columns = member_client.get("/").context["columns"]
        return [
            card["application"].pk
            for col in columns
            for card in col["cards"]
            if "application" in card
        ]

    before = due - timedelta(microseconds=1)
    monkeypatch.setattr(timezone, "now", lambda: before)
    admin_client.post(detail + "questions/", {"text": "Any update?"})
    admin_client.post(detail + "status/", {"status": outcome})
    assert application.pk in board_ids()
    assert not member_client.get("/grants/archive/").context["applications"]

    monkeypatch.setattr(timezone, "now", lambda: due)
    assert application.pk not in board_ids()
    archive = member_client.get("/grants/archive/")
    assert list(archive.context["applications"]) == [application]
    assert b"Decision by staff9" in archive.content
    assert b"staff9" in admin_client.get(detail).content
    assert OutboxEvent.objects.filter(type="application.status_changed").count() == 1

    other = "rejected" if outcome == "approved" else "approved"
    admin_client.post(detail + "status/", {"status": other})
    application.refresh_from_db()
    assert str(application.decided_by) == "staff1"
    assert application.decided_at == due
    assert application.archive_at == archive_time(due)
    assert application.pk in board_ids()
    admin_client.post(detail + "status/", {"status": "under_review"})
    application.refresh_from_db()
    assert application.decided_by is application.decided_at is application.archive_at is None


def test_archive_search_filters_and_order(
    make_application: Callable[..., Application], member_client: Client
) -> None:
    earlier = make_application(name="Maya Okafor")
    later = make_application(grant=earlier.grant, name="Avery Chen")
    later.answers = {"project_title": "Arctic field studies"}
    now = timezone.now()
    for application, outcome, days in [(earlier, "approved", 10), (later, "rejected", 2)]:
        application.status = outcome
        application.decided_at = now - timedelta(days=40 + days)
        application.archive_at = archive_time(application.decided_at)
        application.save()
    archive = "/grants/archive/"
    assert list(member_client.get(archive).context["applications"]) == [later, earlier]
    assert list(member_client.get(archive, {"sort": "oldest"}).context["applications"]) == [
        earlier,
        later,
    ]
    for query in ["ArCTic", "avery"]:
        response = member_client.get(archive, {"q": query})
        assert list(response.context["applications"]) == [later]
        assert b"Arctic field studies" in response.content
    response = member_client.get(archive, {"q": earlier.grant.title, "status": "approved"})
    assert list(response.context["applications"]) == [earlier]
    assert response.context["total"] == 2
    assert b"No archived applications match" in member_client.get(archive, {"q": "missing"}).content


def test_archive_requires_org_membership(client: Client, make_user: Callable[..., Any]) -> None:
    assert client.get("/grants/archive/").status_code == 302
    client.force_login(make_user("outsider"))
    assert client.get("/grants/archive/").status_code == 403
