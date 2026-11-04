import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.formschema import BASE_FIELDS, FIELD_TYPES
from it42.common.models import OutboxEvent
from it42.org.grants import services
from it42.org.grants.models import Grant

BUDGET = {"name": "budget", "label": "Budget", "type": "number", "required": True}
SCHEMA = [*BASE_FIELDS, BUDGET]


def grant_data(**overrides: Any) -> dict[str, str]:
    data = {
        "title": "g1",
        "description": "Solar research",
        "deadline": (timezone.localdate() + timedelta(days=30)).isoformat(),
        "form_schema": json.dumps(SCHEMA),
    }
    data.update(overrides)
    return data


@pytest.fixture
def draft(make_user: Callable[..., Any]) -> Grant:
    return Grant.objects.create(
        title="g1",
        description="d",
        deadline=timezone.localdate() + timedelta(days=30),
        form_schema=SCHEMA,
        created_by=make_user("creator"),
    )


def test_admin_creates_a_draft(admin_client: Client) -> None:
    response = admin_client.post("/grants/new/", grant_data())
    assert response.status_code == 302
    grant = Grant.objects.get()
    assert grant.status == Grant.Status.DRAFT
    assert grant.form_schema == SCHEMA
    assert not OutboxEvent.objects.exists()


def test_new_grant_page_has_the_builder_and_the_starting_template(admin_client: Client) -> None:
    body = admin_client.get("/grants/new/").content.decode()
    assert 'id="form-builder"' in body and "it42/formbuilder.js" in body
    config = json.loads(
        body.split('id="builder-config"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    )
    assert [w["type"] for w in config["widgets"]] == list(FIELD_TYPES)
    assert config["locked"] == ["applicant_name", "applicant_email", "administrating_organisation"]
    # Only the administrating organisation may be made optional, and it is not on the palette.
    assert config["optional"] == ["administrating_organisation"]
    assert [w["type"] for w in config["widgets"] if not w["palette"]] == ["research_org"]
    assert config["max_fields"] == 30
    # The JSON textarea (what the builder edits and the server reads) starts from the template.
    textarea = body.split('name="form_schema"', 1)[1].split("</textarea>", 1)[0]
    assert "applicant_name" in textarea and "applicant_email" in textarea
    assert "administrating_organisation" in textarea
    assert "budget" not in textarea


def test_edit_page_loads_the_saved_schema(admin_client: Client, draft: Grant) -> None:
    body = admin_client.get(f"/grants/{draft.pk}/edit/").content.decode()
    assert "&quot;budget&quot;" in body


def test_rich_schema_round_trips(admin_client: Client) -> None:
    schema = [
        *BASE_FIELDS,
        {"name": "about", "label": "About the project", "type": "heading"},
        {
            "name": "area",
            "label": "Area",
            "type": "select",
            "required": True,
            "options": ["Energy", "Water"],
        },
        {"name": "topics", "label": "Topics", "type": "checkboxes", "options": ["AI", "Bio"]},
        {"label": "Years", "type": "integer", "min": 1, "max": 5},
        {"name": "agree", "label": "I agree to the terms", "type": "checkbox", "required": True},
    ]
    response = admin_client.post("/grants/new/", grant_data(form_schema=json.dumps(schema)))
    assert response.status_code == 302
    saved = Grant.objects.get().form_schema
    # Names are derived from the labels, whatever the JSON said.
    assert [f["name"] for f in saved] == [
        "applicant_name",
        "applicant_email",
        "administrating_organisation",
        "about_the_project",
        "area",
        "topics",
        "years",
        "i_agree_to_the_terms",
    ]
    assert saved[4] == {**schema[4], "name": "area"}


def test_names_are_never_taken_from_the_user(admin_client: Client) -> None:
    schema = [
        {"name": "documents", "label": "Budget (SEK)", "type": "number"},
        {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
        {"name": "Not Valid", "label": "Budget (SEK)", "type": "text"},
        {"name": "applicant_email", "label": "Email", "type": "email", "required": True},
        {"name": "org", "label": "Administrating organisation", "type": "research_org"},
    ]
    response = admin_client.post("/grants/new/", grant_data(form_schema=json.dumps(schema)))
    assert response.status_code == 302
    assert [f["name"] for f in Grant.objects.get().form_schema] == [
        "budget_sek",
        "applicant_name",
        "budget_sek_2",
        "applicant_email",
        "administrating_organisation",
    ]


@pytest.mark.parametrize(
    "schema",
    [
        '[{"name": "Bad"}]',
        '[{"label": "x", "type": "nope"}]',
        json.dumps([BUDGET]),
        json.dumps([BASE_FIELDS[0], BUDGET]),
        json.dumps([BASE_FIELDS[0], {**BASE_FIELDS[1], "required": False}]),
        json.dumps([{**BASE_FIELDS[0], "type": "textarea"}, BASE_FIELDS[1]]),
        json.dumps([*BASE_FIELDS, {"name": "x", "label": "x", "type": "select", "options": []}]),
    ],
    ids=[
        "no-label",
        "bad-type",
        "no-base",
        "no-email",
        "email-optional",
        "name-not-text",
        "bad-options",
    ],
)
def test_invalid_schema_is_refused(admin_client: Client, schema: str) -> None:
    response = admin_client.post("/grants/new/", grant_data(form_schema=schema))
    assert response.status_code == 200
    assert b"data-schema-error" in response.content
    assert not Grant.objects.exists()


def test_past_deadline_is_refused(admin_client: Client) -> None:
    response = admin_client.post("/grants/new/", grant_data(deadline="2020-01-01"))
    assert response.status_code == 200
    assert not Grant.objects.exists()


def test_reviewer_cannot_create(client: Client, make_member: Callable[..., Any]) -> None:
    client.force_login(make_member("a1"))
    assert client.post("/grants/new/", grant_data()).status_code == 403
    assert client.get("/grants/").status_code == 200


def test_publish_emits_grant_published(admin_client: Client, draft: Grant) -> None:
    admin_client.post(f"/grants/{draft.pk}/publish/")
    draft.refresh_from_db()
    assert draft.status == Grant.Status.PUBLISHED
    event = OutboxEvent.objects.get()
    assert (event.exchange, event.type, event.grant_id) == (
        "o1-to-core",
        "grant.published",
        draft.public_id,
    )
    assert event.payload["grant_public_id"] == str(draft.public_id)
    assert event.payload["form_schema"] == SCHEMA
    assert event.payload["org_name"] == "Org 1"


def test_publish_refuses_a_form_without_the_base_fields(admin_client: Client, draft: Grant) -> None:
    draft.form_schema = [BUDGET]
    draft.save()
    response = admin_client.post(f"/grants/{draft.pk}/publish/", follow=True)
    assert b"applicant_name" in response.content
    draft.refresh_from_db()
    assert draft.status == Grant.Status.DRAFT
    assert not OutboxEvent.objects.exists()


def test_published_grant_cannot_be_edited_or_republished(
    admin_client: Client, draft: Grant
) -> None:
    services.publish(draft.pk)
    admin_client.post(f"/grants/{draft.pk}/edit/", grant_data(title="changed"))
    draft.refresh_from_db()
    assert draft.title == "g1"
    with pytest.raises(services.InvalidTransition):
        services.publish(draft.pk)
    assert OutboxEvent.objects.count() == 1


def test_close_emits_grant_closed(admin_client: Client, draft: Grant) -> None:
    with pytest.raises(services.InvalidTransition):
        services.close(draft.pk)
    services.publish(draft.pk)
    admin_client.post(f"/grants/{draft.pk}/close/")
    draft.refresh_from_db()
    assert draft.status == Grant.Status.CLOSED
    assert list(OutboxEvent.objects.values_list("type", flat=True)) == [
        "grant.published",
        "grant.closed",
    ]


def test_dashboard_lists_published_grants(admin_client: Client, draft: Grant) -> None:
    services.publish(draft.pk)
    response = admin_client.get("/")
    assert b"g1" in response.content
