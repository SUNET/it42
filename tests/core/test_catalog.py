import json
import uuid
from datetime import date, time, timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.core.catalog.models import PublicGrant
from it42.core.catalog.views import is_open

SCHEMA = [{"name": "budget", "label": "Budget", "type": "number", "required": True}]


def published(grant_id: uuid.UUID, **payload: Any) -> bytes:
    body = {
        "grant_public_id": str(grant_id),
        "org_name": "Org 1",
        "title": "g1",
        "description": "Solar research",
        "deadline": (timezone.localdate() + timedelta(days=30)).isoformat(),
        "form_schema": SCHEMA,
    }
    body.update(payload)
    return Envelope(type="grant.published", payload=body, grant_id=grant_id).to_json()


@pytest.mark.django_db
def test_grant_published_creates_public_grant() -> None:
    grant_id = uuid.uuid4()
    process(published(grant_id), "o1-to-core")
    grant = PublicGrant.objects.get()
    assert (grant.org_slug, grant.org_name, grant.grant_public_id) == ("o1", "Org 1", grant_id)
    assert grant.status == PublicGrant.Status.OPEN


@pytest.mark.django_db
def test_grant_published_accepts_every_widget_type() -> None:
    schema = [
        {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
        {"name": "applicant_email", "label": "Email", "type": "email", "required": True},
        {"name": "about", "label": "About", "type": "heading"},
        {"name": "area", "label": "Area", "type": "select", "options": ["Energy", "Water"]},
        {"name": "topics", "label": "Topics", "type": "checkboxes", "options": ["AI"]},
        {"name": "years", "label": "Years", "type": "integer", "min": 1, "max": 5},
        {"name": "agree", "label": "I agree", "type": "checkbox"},
    ]
    process(published(uuid.uuid4(), form_schema=schema), "o1-to-core")
    assert PublicGrant.objects.get().form_schema == [
        {**spec, "required": spec.get("required", False)} for spec in schema
    ]


@pytest.mark.django_db
def test_org_name_comes_from_the_queue_not_the_payload() -> None:
    process(published(uuid.uuid4(), org_name="Org 2"), "o1-to-core")
    assert PublicGrant.objects.get().org_name == "Org 1"


@pytest.mark.django_db
def test_two_orgs_with_the_same_grant_id_do_not_collide() -> None:
    grant_id = uuid.uuid4()
    process(published(grant_id, title="from o1"), "o1-to-core")
    process(published(grant_id, title="from o2"), "o2-to-core")
    assert PublicGrant.objects.get(org_slug="o1").title == "from o1"
    assert PublicGrant.objects.get(org_slug="o2").title == "from o2"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"form_schema": [{"name": "Bad"}]},
        {"form_schema": [{"name": "a", "label": "x", "type": "select", "options": []}]},
        {"form_schema": [{"name": "a", "label": "x", "type": "file"}]},
        {"deadline": "soon"},
        {"title": ""},
        {"title": 5},
    ],
)
def test_invalid_grants_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(RejectEvent):
        process(published(uuid.uuid4(), **payload), "o1-to-core")
    assert not PublicGrant.objects.exists()


@pytest.mark.django_db
def test_grant_closed_only_affects_the_senders_grant() -> None:
    grant_id = uuid.uuid4()
    process(published(grant_id), "o1-to-core")
    forged = Envelope(
        type="grant.closed", payload={"grant_public_id": str(grant_id)}, grant_id=grant_id
    ).to_json()
    with pytest.raises(RejectEvent):
        process(forged, "o2-to-core")
    assert PublicGrant.objects.get().status == PublicGrant.Status.OPEN
    process(Envelope(type="grant.closed", payload={}, grant_id=grant_id).to_json(), "o1-to-core")
    assert PublicGrant.objects.get().status == PublicGrant.Status.CLOSED


def make(org: str, title: str, deadline: date, status: str = "open") -> PublicGrant:
    return PublicGrant.objects.create(
        org_slug=org,
        org_name={"o1": "Org 1", "o2": "Org 2"}[org],
        grant_public_id=uuid.uuid4(),
        title=title,
        description="d",
        deadline=deadline,
        status=status,
    )


@pytest.mark.django_db
def test_home_lists_open_grants_from_all_orgs(client: Client) -> None:
    future = timezone.localdate() + timedelta(days=5)
    make("o1", "g1", future)
    make("o2", "g2", future)
    make("o1", "closed-grant", future, status="closed")
    make("o1", "expired-grant", timezone.localdate() - timedelta(days=1))
    body = client.get("/").content.decode()
    assert "g1" in body and "g2" in body
    assert "Org 1" in body and "Org 2" in body
    assert "closed-grant" not in body and "expired-grant" not in body


@pytest.mark.django_db
def test_grant_detail_asks_anonymous_users_to_log_in(client: Client) -> None:
    grant = make("o1", "g1", timezone.localdate() + timedelta(days=5))
    body = client.get(f"/grants/o1/{grant.grant_public_id}/").content.decode()
    assert "Log in to apply" in body
    assert client.get(f"/grants/o2/{grant.grant_public_id}/").status_code == 404


def test_envelope_grant_id_must_match_payload() -> None:
    raw = json.loads(published(uuid.uuid4()))
    raw["grant_id"] = str(uuid.uuid4())
    with pytest.raises(RejectEvent):
        Envelope.from_json(json.dumps(raw).encode())


@pytest.mark.django_db
def test_calls_page_searches_and_filters_by_funder(client: Client) -> None:
    future = timezone.localdate() + timedelta(days=40)
    make("o1", "Solar cells", future)
    make("o2", "Ocean data", future)
    body = client.get("/calls/").content.decode()
    assert "Solar cells" in body and "Ocean data" in body
    assert "2 grants accepting applications" in body
    body = client.get("/calls/", {"q": "solar"}).content.decode()
    assert "Solar cells" in body and "Ocean data" not in body
    body = client.get("/calls/", {"funder": "o2"}).content.decode()
    assert "Ocean data" in body and "Solar cells" not in body
    # An unknown funder is ignored rather than trusted.
    body = client.get("/calls/", {"funder": "evil"}).content.decode()
    assert "Solar cells" in body and "Ocean data" in body


@pytest.mark.django_db
def test_calls_page_shows_closing_soon_section(client: Client) -> None:
    make("o1", "Soon", timezone.localdate() + timedelta(days=3))
    body = client.get("/calls/").content.decode()
    assert "Closing soon" in body and "Closes in 3 days" in body


@pytest.mark.django_db
def test_home_links_to_open_calls_and_funders(client: Client) -> None:
    make("o1", "g1", timezone.localdate() + timedelta(days=5))
    body = client.get("/").content.decode()
    assert 'href="/calls/"' in body and 'Apply <span class="it-accent">right now</span>' in body
    assert 'href="/calls/?funder=o1"' in body and 'href="/calls/?funder=o2"' in body


def test_text_pages_render_markdown(client: Client) -> None:
    body = client.get("/pages/cookies/").content.decode()
    assert "<h1>Cookie policy</h1>" in body
    assert "<table>" in body and "sessionid" in body
    assert 'href="#cookies-we-use"' in body  # "On this page"
    assert client.get("/pages/nope/").status_code == 404
    assert client.get("/pages/privacy/").status_code == 200


@pytest.mark.django_db
def test_grant_published_keeps_the_closing_time_and_the_new_blocks() -> None:
    schema = [
        {"name": "closes", "label": "Application deadline", "type": "deadline"},
        {"name": "call", "label": "Funder website", "type": "link", "url": "https://x.example"},
        {"name": "costs", "label": "Budget", "type": "budget", "max_award": 75000},
        {
            "name": "plan",
            "label": "Plan",
            "type": "textarea",
            "max_words": 1500,
            "description": "d",
        },
    ]
    process(published(uuid.uuid4(), deadline_time="17:00", form_schema=schema), "o1-to-core")
    grant = PublicGrant.objects.get()
    assert grant.deadline_time == time(17, 0)
    assert grant.form_schema[2]["currency"] == "SEK" and grant.form_schema[3]["max_words"] == 1500
    # Orgs that don't send a time (older images) still publish.
    process(published(uuid.uuid4(), title="no time"), "o1-to-core")
    assert PublicGrant.objects.get(title="no time").deadline_time is None
    with pytest.raises(RejectEvent):
        process(published(uuid.uuid4(), deadline_time="five"), "o1-to-core")


@pytest.mark.django_db
def test_calls_close_at_the_given_time_of_the_deadline_day(client: Client) -> None:
    today = timezone.localdate()
    now = timezone.localtime()
    later = make("o1", "Later today", today)
    later.deadline_time = (now + timedelta(hours=1)).time()
    later.save()
    earlier = make("o1", "Earlier today", today)
    earlier.deadline_time = (now - timedelta(hours=1)).time()
    earlier.save()
    all_day = make("o1", "All day", today)
    assert is_open(later) and is_open(all_day) and not is_open(earlier)
    assert all_day.closes_at().time() == time.max
    assert timezone.localtime(later.closes_at()).time() == later.deadline_time
    # The list stays by day; the detail page says a call that closed earlier today is closed.
    body = client.get("/calls/").content.decode()
    assert "Later today" in body and "Earlier today" in body
    body = client.get(f"/grants/o1/{earlier.grant_public_id}/").content.decode()
    assert "Log in to apply" not in body and "closed for applications" in body
    body = client.get(f"/grants/o1/{later.grant_public_id}/").content.decode()
    assert "Log in to apply" in body and later.deadline_time.strftime("%H:%M") in body


@pytest.mark.django_db
def test_grant_detail_lists_only_the_inputs(client: Client) -> None:
    grant = make("o1", "g1", timezone.localdate() + timedelta(days=5))
    grant.form_schema = [
        {"name": "intro", "label": "Read this first", "type": "paragraph"},
        {"name": "closes", "label": "Application deadline", "type": "deadline"},
        {"name": "call", "label": "Funder website", "type": "link", "url": "https://x.example"},
        {"name": "plan", "label": "Project plan", "type": "textarea", "required": True},
    ]
    grant.save()
    body = client.get(f"/grants/o1/{grant.grant_public_id}/").content.decode()
    asks = body.split('id="asks-for"', 1)[1].split("</section>", 1)[0]
    assert "Project plan" in asks
    for hidden in ("Read this first", "Application deadline", "Funder website"):
        assert hidden not in asks
