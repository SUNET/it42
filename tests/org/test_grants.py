import json
from collections.abc import Callable
from datetime import time, timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.formschema import BASE_FIELDS, DEFAULT_FIELDS, FIELD_TYPES
from it42.common.models import OutboxEvent
from it42.org.grants import services
from it42.org.grants.models import Category, Folder, FormTemplate, Grant
from it42.org.grants.templates import BUILTIN_TEMPLATES

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


def builder_config(body: str) -> dict[str, Any]:
    return json.loads(
        body.split('id="builder-config"', 1)[1].split(">", 1)[1].split("</script>", 1)[0]
    )


@pytest.fixture
def draft(make_user: Callable[..., Any]) -> Grant:
    return Grant.objects.create(
        title="g1",
        description="d",
        deadline=timezone.localdate() + timedelta(days=30),
        form_schema=SCHEMA,
        created_by=make_user("creator"),
    )


def test_admin_creates_a_draft_from_a_plain_post(admin_client: Client) -> None:
    # Exactly what scripts/acceptance.py sends: no time, folder, category or template.
    response = admin_client.post("/grants/new/", grant_data())
    assert response.status_code == 302 and response["Location"] == "/grants/"
    grant = Grant.objects.get()
    assert grant.status == Grant.Status.DRAFT
    assert grant.form_schema == SCHEMA
    assert grant.deadline_time == time(17, 0)
    assert grant.folder is None and grant.category is None and grant.template is None
    assert not OutboxEvent.objects.exists()


def test_new_grant_page_has_the_builder_and_the_starting_template(admin_client: Client) -> None:
    body = admin_client.get("/grants/new/").content.decode()
    assert 'id="grant-form"' in body and "it42/formbuilder.js" in body
    config = builder_config(body)
    assert [w["type"] for w in config["widgets"]] == list(FIELD_TYPES)
    assert config["locked"] == ["applicant_name", "applicant_email", "administrating_organisation"]
    # Only the administrating organisation may be made optional; it and the typed web
    # address are not on the palette.
    assert config["optional"] == ["administrating_organisation"]
    assert [w["type"] for w in config["widgets"] if not w["palette"]] == ["url", "research_org"]
    assert config["defaults"] == ["grant_summary", "application_deadline", "funder_website"]
    assert config["max_fields"] == 30 and config["currencies"][0] == "SEK"
    assert [t["name"] for t in config["templates"]] == [t["name"] for t in BUILTIN_TEMPLATES]
    assert config["templates"][0]["builtin"] and config["based_on"] is None
    assert [f["name"] for f in config["start"]] == [
        *(f["name"] for f in BASE_FIELDS),
        *(f["name"] for f in DEFAULT_FIELDS),
    ]
    # The palette is rendered server-side, with the saved templates first.
    palette = body.split("data-palette>", 1)[1].split("data-palette-empty", 1)[0]
    assert 'data-template="' in palette and 'data-type="budget"' in palette
    assert palette.index("Saved templates") < palette.index("Short text")
    # The JSON textarea (what the builder edits and the server reads) starts from the
    # blank form: base fields and defaults.
    textarea = body.split('name="form_schema"', 1)[1].split("</textarea>", 1)[0]
    for name in ("applicant_name", "applicant_email", "administrating_organisation"):
        assert name in textarea
    assert "grant_summary" in textarea and "funder_website" in textarea
    assert "budget" not in textarea
    # Buttons that submit the same form elsewhere.
    assert 'formaction="/grants/new/?action=publish"' in body
    assert 'formaction="/grants/new/?action=preview" formtarget="_blank"' in body
    assert 'formaction="/grants/new/?action=template"' in body
    assert "Duplicate form" not in body


def test_edit_page_loads_the_saved_schema(admin_client: Client, draft: Grant) -> None:
    body = admin_client.get(f"/grants/{draft.pk}/edit/").content.decode()
    assert "&quot;budget&quot;" in body
    assert f'formaction="/grants/{draft.pk}/duplicate/"' in body
    assert f'formaction="/grants/{draft.pk}/edit/?action=publish"' in body


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
        {"label": "Budget breakdown", "type": "budget", "max_award": 75000, "currency": "EUR"},
        {"label": "Application deadline", "type": "deadline", "description": "Closes then"},
        {"label": "Funder website", "type": "link", "url": "https://formas.example/call"},
        {
            "label": "Plan",
            "type": "textarea",
            "max_words": 1500,
            "description": "Up to 1,500 words",
        },
    ]
    response = admin_client.post(
        "/grants/new/",
        grant_data(form_schema=json.dumps(schema), deadline_time="16:30"),
    )
    assert response.status_code == 302
    grant = Grant.objects.get()
    assert grant.deadline_time == time(16, 30)
    saved = grant.form_schema
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
        "budget_breakdown",
        "application_deadline",
        "funder_website",
        "plan",
    ]
    assert saved[4] == {**schema[4], "name": "area"}
    assert saved[8]["currency"] == "EUR" and saved[8]["max_award"] == 75000
    assert saved[10]["url"] == "https://formas.example/call"
    assert saved[11]["max_words"] == 1500 and saved[11]["description"] == "Up to 1,500 words"


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
        json.dumps([*BASE_FIELDS, {"label": "x", "type": "budget", "currency": "NOK"}]),
        json.dumps([*BASE_FIELDS, {"label": "x", "type": "link", "url": "nope"}]),
    ],
    ids=[
        "no-label",
        "bad-type",
        "no-base",
        "no-email",
        "email-optional",
        "name-not-text",
        "bad-options",
        "bad-currency",
        "bad-url",
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
    assert client.get("/grants/drafts/").status_code == 200
    assert client.post("/grants/folders/new/", {"name": "x"}).status_code == 403
    assert client.post("/grants/categories/new/", {"name": "x"}).status_code == 403
    assert not Folder.objects.exists() and not Category.objects.exists()


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
    assert event.payload["deadline_time"] == "17:00"


def test_publish_refuses_a_form_without_the_base_fields(admin_client: Client, draft: Grant) -> None:
    draft.form_schema = [BUDGET]
    draft.save()
    response = admin_client.post(f"/grants/{draft.pk}/publish/", follow=True)
    assert b"applicant_name" in response.content
    draft.refresh_from_db()
    assert draft.status == Grant.Status.DRAFT
    assert not OutboxEvent.objects.exists()


def test_publish_refuses_a_link_without_its_address(admin_client: Client, draft: Grant) -> None:
    draft.form_schema = [*BASE_FIELDS, *DEFAULT_FIELDS]  # the funder website has no url yet
    draft.save()
    response = admin_client.post(f"/grants/{draft.pk}/publish/", follow=True)
    assert b"Funder website" in response.content and b"web address" in response.content
    draft.refresh_from_db()
    assert draft.status == Grant.Status.DRAFT and not OutboxEvent.objects.exists()


def test_publish_from_the_builder_saves_then_publishes(admin_client: Client) -> None:
    response = admin_client.post("/grants/new/?action=publish", grant_data(title="Published"))
    grant = Grant.objects.get()
    assert response.status_code == 302 and response["Location"] == f"/grants/{grant.pk}/published/"
    assert grant.title == "Published" and grant.status == Grant.Status.PUBLISHED
    assert OutboxEvent.objects.get().type == "grant.published"
    # A form that cannot be published yet is still saved as a draft.
    schema = json.dumps([*BASE_FIELDS, *DEFAULT_FIELDS])
    response = admin_client.post(
        "/grants/new/?action=publish", grant_data(title="Not yet", form_schema=schema)
    )
    draft = Grant.objects.get(title="Not yet")
    assert response.status_code == 302 and response["Location"] == f"/grants/{draft.pk}/edit/"
    assert draft.status == Grant.Status.DRAFT and OutboxEvent.objects.count() == 1


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


# ---- Saved templates ----------------------------------------------------------------------


def test_the_builtin_template_is_seeded_and_protected(admin_client: Client) -> None:
    template = FormTemplate.objects.get(builtin_key="standard-research-grant")
    assert template.builtin_key == BUILTIN_TEMPLATES[0]["key"] and template.is_builtin
    assert template.name == "Standard research grant"
    assert template.field_count == len(template.form_schema) - len(BASE_FIELDS) == 8
    assert admin_client.post(f"/grants/templates/{template.pk}/delete/").status_code == 302
    assert (
        admin_client.post(f"/grants/templates/{template.pk}/rename/", {"name": "x"}).status_code
        == 302
    )
    template.refresh_from_db()
    assert template.name == "Standard research grant"
    body = admin_client.get("/grants/templates/").content.decode()
    assert "Built-in" in body and "Delete" not in body.split("Standard research grant", 1)[1][:600]


def test_save_as_template_saves_the_draft_and_links_it(admin_client: Client) -> None:
    response = admin_client.post(
        "/grants/new/?action=template", grant_data(title="Coastal", name="Climate 2026")
    )
    grant = Grant.objects.get()
    assert response.status_code == 302 and response["Location"] == f"/grants/{grant.pk}/edit/"
    template = FormTemplate.objects.get(name="Climate 2026")
    assert not template.is_builtin and template.form_schema == SCHEMA
    assert grant.template == template
    # The template is offered on every builder page, and "used" counts this grant.
    config = builder_config(admin_client.get(f"/grants/{grant.pk}/edit/").content.decode())
    mine = next(t for t in config["templates"] if t["name"] == "Climate 2026")
    assert mine["used"] == 1 and mine["schema"] == SCHEMA and config["based_on"] == template.pk
    # A second one with the same name is refused and nothing is saved.
    response = admin_client.post("/grants/new/?action=template", grant_data(name="climate 2026"))
    assert response.status_code == 200 and Grant.objects.count() == 1
    assert b"already one called" in response.content
    # Missing name: same.
    response = admin_client.post("/grants/new/?action=template", grant_data())
    assert response.status_code == 200 and Grant.objects.count() == 1


def test_rename_and_delete_own_templates(admin_client: Client, draft: Grant) -> None:
    template = FormTemplate.objects.create(name="Mine", form_schema=SCHEMA)
    draft.template = template
    draft.save()
    admin_client.post(f"/grants/templates/{template.pk}/rename/", {"name": "  Ours  "})
    template.refresh_from_db()
    assert template.name == "Ours"
    response = admin_client.post(
        f"/grants/templates/{template.pk}/rename/", {"name": "Standard research grant"}, follow=True
    )
    assert b"already one called" in response.content
    admin_client.post(f"/grants/templates/{template.pk}/delete/")
    assert not FormTemplate.objects.filter(pk=template.pk).exists()
    draft.refresh_from_db()
    assert draft.template is None and draft.form_schema == SCHEMA


# ---- Duplicate and preview -----------------------------------------------------------------


def test_duplicate_makes_a_new_draft_with_the_same_form(admin_client: Client, draft: Grant) -> None:
    folder = Folder.objects.create(name="Water")
    draft.folder = folder
    draft.deadline = timezone.localdate() - timedelta(days=1)  # an old grant
    draft.save()
    services.publish(draft.pk)
    response = admin_client.post(f"/grants/{draft.pk}/duplicate/")
    copy = Grant.objects.exclude(pk=draft.pk).get()
    assert response.status_code == 302 and response["Location"] == f"/grants/{copy.pk}/edit/"
    assert copy.title == "Copy of g1" and copy.status == Grant.Status.DRAFT
    assert copy.form_schema == SCHEMA and copy.folder == folder
    assert copy.deadline == timezone.localdate()
    assert admin_client.get(f"/grants/{draft.pk}/duplicate/").status_code == 405


def test_preview_renders_the_posted_form_without_saving(admin_client: Client) -> None:
    schema = [
        *BASE_FIELDS,
        {"label": "Grant summary", "type": "text", "description": "One or two sentences"},
        {"label": "Application deadline", "type": "deadline"},
        {"label": "Funder website", "type": "link", "url": "https://formas.example/call"},
        {"label": "Project plan", "type": "heading"},
        {"label": "Methods", "type": "textarea", "required": True, "max_words": 1000},
        {"label": "Budget breakdown", "type": "budget", "max_award": 75000},
    ]
    data = grant_data(
        title="Coastal Futures", form_schema=json.dumps(schema), deadline_time="17:00"
    )
    response = admin_client.post("/grants/new/?action=preview", data)
    assert response.status_code == 200 and not Grant.objects.exists()
    body = response.content.decode()
    # The design's page: dark bar, the call's header card with chips, numbered questions.
    assert "Preview — this is what applicants will see" in body and "Back to editing" in body
    assert "Coastal Futures" in body and "Open call · Org 1" in body
    assert "Closes 31" not in body and ", 17:00" in body  # the posted date, not the design's
    assert "Up to 75" in body and "000 SEK" in body and 'href="https://formas.example/call"' in body
    assert "formas.example" in body
    assert "3 questions · 1 required" in body
    assert (
        "1. Your name" not in body and "1. Grant summary" in body and "3. Budget breakdown" in body
    )
    assert "One or two sentences" in body and "Project plan" in body
    assert (
        'class="it-preview-pill is-required" data-question-state>Required' in body
        and ">Optional<" in body
    )
    assert 'data-max-words="1000"' in body and "it42/wordcount.js" in body
    assert 'data-budget="true"' in body and "it42/budget.js" in body
    assert "Submit is turned off in preview" in body
    # Funder blocks are chips, not questions.
    assert "Application deadline" not in body.split("it-preview-form", 1)[1]
    # The builder's overlay asks for the embedded page: no bar; a bad schema is a 400.
    body = admin_client.post("/grants/new/?action=preview&embed=1", data).content.decode()
    assert '<header class="it-preview-bar">' not in body and "3 questions" in body
    response = admin_client.post(
        "/grants/new/?action=preview&embed=1", grant_data(form_schema="[1]")
    )
    assert response.status_code == 400 and b"cannot be previewed" in response.content
    # Without the overlay an invalid schema comes back to the builder with the error.
    response = admin_client.post("/grants/new/?action=preview", grant_data(form_schema="[1]"))
    assert response.status_code == 200 and b"cannot be previewed" in response.content


# ---- Drafts page, folders and categories ---------------------------------------------------


def test_drafts_page_lists_folders_and_filters_grants(admin_client: Client, draft: Grant) -> None:
    water = Folder.objects.create(name="Water & soil")
    Folder.objects.create(name="Archive")
    draft.folder = water
    draft.category = Category.objects.create(name="Clean water")
    draft.save()
    other = Grant.objects.create(
        title="Published one",
        description="d",
        deadline=timezone.localdate() + timedelta(days=3),
        form_schema=SCHEMA,
        folder=water,
        created_by=draft.created_by,
    )
    services.publish(other.pk)
    body = admin_client.get("/grants/drafts/").content.decode()
    assert "Water &amp; soil" in body and "Archive" in body
    assert "2 folders · 2 grants" in body and "2 grants · 1 published" in body
    assert "g1" in body and "Published one" in body and "Clean water" in body
    assert "1 field · Edited" in body  # the budget: base fields are not counted
    assert 'href="/grants/new/"' in body and "Create a grant" in body
    body = admin_client.get(
        f"/grants/drafts/?folder={water.pk}&status=unpublished"
    ).content.decode()
    assert "g1" in body and "Published one" not in body
    body = admin_client.get(f"/grants/drafts/?folder={water.pk}&status=published").content.decode()
    assert "Published one" in body and ">g1<" not in body
    assert admin_client.get("/grants/drafts/?folder=999&status=odd").status_code == 200


def test_folders_and_categories_are_created_renamed_and_deleted(
    admin_client: Client, draft: Grant
) -> None:
    response = admin_client.post("/grants/folders/new/", {"name": "  Marine  biology "})
    folder = Folder.objects.get()
    assert (
        response.status_code == 302
        and response["Location"] == f"/grants/drafts/?folder={folder.pk}"
    )
    assert folder.name == "Marine biology"
    response = admin_client.post("/grants/folders/new/", {"name": "marine BIOLOGY"}, follow=True)
    assert b"already one called" in response.content and Folder.objects.count() == 1
    admin_client.post(f"/grants/folders/{folder.pk}/rename/", {"name": "Sea"})
    folder.refresh_from_db()
    assert folder.name == "Sea"
    draft.folder = folder
    draft.save()
    admin_client.post(f"/grants/folders/{folder.pk}/delete/")
    draft.refresh_from_db()
    assert not Folder.objects.exists() and draft.folder is None  # the grant is kept

    admin_client.post("/grants/categories/new/", {"name": "Hydrology"})
    category = Category.objects.get()
    body = admin_client.get("/grants/categories/").content.decode()
    assert "Hydrology" in body
    admin_client.post(f"/grants/categories/{category.pk}/rename/", {"name": "Clean water"})
    category.refresh_from_db()
    assert category.name == "Clean water"
    # The builder's Grant settings offer it, and a saved grant keeps it.
    body = admin_client.get("/grants/new/").content.decode()
    assert f'<option value="{category.pk}">Clean water</option>' in body
    admin_client.post("/grants/new/", grant_data(category=str(category.pk)))
    assert Grant.objects.get(title="g1", category=category)
    admin_client.post(f"/grants/categories/{category.pk}/delete/")
    assert not Category.objects.exists()
    assert Grant.objects.filter(title="g1", category=None).count() == 2


def test_duplicate_uses_unsaved_builder_values(admin_client: Client, draft: Grant) -> None:
    response = admin_client.post(
        f"/grants/{draft.pk}/duplicate/", grant_data(title="Unsaved title")
    )
    copy = Grant.objects.exclude(pk=draft.pk).get()
    assert response["Location"] == f"/grants/{copy.pk}/edit/"
    assert copy.title == "Copy of Unsaved title" and copy.form_schema == SCHEMA
    draft.refresh_from_db()
    assert draft.title == "g1"
    response = admin_client.post(f"/grants/{draft.pk}/duplicate/", grant_data(form_schema="[1]"))
    assert response.status_code == 200 and Grant.objects.count() == 2


def test_published_form_is_read_only_and_admin_only(
    admin_client: Client, member_client: Client, draft: Grant
) -> None:
    url = f"/grants/{draft.pk}/published/"
    assert admin_client.get(url).status_code == 404
    services.publish(draft.pk)
    response = admin_client.get(url)
    assert response.status_code == 200
    assert b"View in Open calls" in response.content and b"Back to grant" in response.content
    assert b"1. Budget" in response.content and b"1. Your name" not in response.content
    assert member_client.get(url).status_code == 403
