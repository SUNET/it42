from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from django import forms

from it42.common.formschema import (
    BASE_FIELDS,
    DEFAULT_FIELDS,
    FIELD_TYPES,
    LAYOUT_TYPES,
    THOUSANDS_SEP,
    WIDGETS,
    SchemaError,
    answers_to_json,
    assign_names,
    build_form,
    display_budget,
    field_name,
    form_layout,
    labelled_answers,
    parse_budget,
    require_base_fields,
    require_publishable,
    validate_schema,
)

SCHEMA = [
    {"name": "title", "label": "Title", "type": "text", "required": True},
    {"name": "summary", "label": "Summary", "type": "textarea"},
    {"name": "budget", "label": "Budget", "type": "number", "required": True},
    {"name": "start", "label": "Start", "type": "date", "required": False},
]

# One entry per widget type, with its optional keys.
EVERY_TYPE = [
    {"name": "about", "label": "About you", "type": "heading"},
    {"name": "intro", "label": "Tell us who you are.", "type": "paragraph"},
    {
        "name": "full_name",
        "label": "Name",
        "type": "text",
        "required": True,
        "placeholder": "Jane Doe",
        "max_length": 100,
        "help_text": "As in your passport.",
    },
    {"name": "bio", "label": "Bio", "type": "textarea", "rows": 3, "max_length": 2000},
    {"name": "email", "label": "Email", "type": "email", "required": True},
    {"name": "site", "label": "Website", "type": "url"},
    {"name": "phone", "label": "Phone", "type": "tel"},
    {"name": "budget", "label": "Budget", "type": "number", "min": 0, "max": 1000000.5},
    {"name": "years", "label": "Years", "type": "integer", "required": True, "min": 1, "max": 5},
    {"name": "start", "label": "Start", "type": "date"},
    {"name": "at", "label": "Time", "type": "time"},
    {"name": "kickoff", "label": "Kick-off", "type": "datetime"},
    {"name": "area", "label": "Area", "type": "select", "options": ["Energy", "Water"]},
    {
        "name": "size",
        "label": "Size",
        "type": "radio",
        "required": True,
        "options": ["Small", "Large"],
    },
    {"name": "topics", "label": "Topics", "type": "checkboxes", "options": ["AI", "Bio", "Sea"]},
    {"name": "agree", "label": "I agree", "type": "checkbox", "required": True},
    {"name": "org", "label": "Organisation", "type": "research_org", "required": True},
    {
        "name": "costs",
        "label": "Budget breakdown",
        "type": "budget",
        "required": True,
        "currency": "SEK",
        "max_award": 75000,
        "max_lines": 3,
        "description": "List the costs you are asking us to cover",
    },
    {"name": "closes", "label": "Application deadline", "type": "deadline"},
    {"name": "call", "label": "Funder website", "type": "link", "url": "https://formas.se/x"},
]


def test_widgets_have_palette_text_and_icons() -> None:
    for widget in WIDGETS.values():
        assert widget["label"] and widget["hint"] and widget["icon"]
    assert [w["group"] for w in WIDGETS.values()] == sorted(
        (w["group"] for w in WIDGETS.values()),
        key=["Text", "Numbers", "Dates", "Choices", "Grant", "Sections"].index,
    )
    assert WIDGETS["url"]["palette"] is False
    assert set(LAYOUT_TYPES) == {"heading", "paragraph", "deadline", "link"}


def test_validate_normalises_defaults() -> None:
    fields = validate_schema(SCHEMA)
    assert fields[1] == {
        "name": "summary",
        "label": "Summary",
        "type": "textarea",
        "required": False,
    }


def test_every_widget_type_validates_and_keeps_its_options() -> None:
    assert {spec["type"] for spec in EVERY_TYPE} == set(FIELD_TYPES) == set(WIDGETS)
    fields = validate_schema(EVERY_TYPE)
    assert fields[2]["placeholder"] == "Jane Doe" and fields[2]["max_length"] == 100
    assert fields[3]["rows"] == 3
    assert fields[7] == {
        "name": "budget",
        "label": "Budget",
        "type": "number",
        "required": False,
        "min": 0,
        "max": 1000000.5,
    }
    assert fields[12]["options"] == ["Energy", "Water"]
    assert fields[0] == {
        "name": "about",
        "label": "About you",
        "type": "heading",
        "required": False,
    }
    assert fields[17] == {
        "name": "costs",
        "label": "Budget breakdown",
        "type": "budget",
        "required": True,
        "currency": "SEK",
        "max_award": 75000,
        "max_lines": 3,
        "description": "List the costs you are asking us to cover",
    }
    assert fields[19]["url"] == "https://formas.se/x"
    # A budget always carries its currency; a link's url may wait until publishing.
    budget, link = validate_schema(
        [
            {"name": "b", "label": "B", "type": "budget"},
            {"name": "l", "label": "L", "type": "link"},
        ]
    )
    assert budget["currency"] == "SEK" and "max_award" not in budget
    assert "url" not in link


def test_textarea_word_limit_and_description() -> None:
    spec = {
        "name": "plan",
        "label": "Plan",
        "type": "textarea",
        "max_words": 3,
        "description": "Up to 3 words",
    }
    assert validate_schema([spec])[0]["max_words"] == 3
    form_class = build_form([spec], forms.Form)
    assert form_class.base_fields["plan"].widget.attrs["data-max-words"] == 3  # wordcount.js
    assert form_class(data={"plan": "one two three"}).is_valid()
    form = form_class(data={"plan": "one two three four"})
    assert not form.is_valid() and "at most 3 words" in form.errors["plan"][0]


@pytest.mark.parametrize(
    "schema",
    [
        {},
        [1],
        [{"name": "Bad Name", "label": "x"}],
        [{"name": "documents", "label": "x"}],
        [{"name": "a", "label": ""}],
        [{"name": "a", "label": "x", "type": "file"}],
        [{"name": "a", "label": "x", "required": "yes"}],
        [{"name": "a", "label": "x"}, {"name": "a", "label": "y"}],
        [{"name": "a", "label": "x", "extra": 1}],
        [{"name": f"f{i}", "label": "x"} for i in range(31)],
        # keys that the type does not take
        [{"name": "a", "label": "x", "type": "date", "placeholder": "p"}],
        [{"name": "a", "label": "x", "type": "text", "options": ["a"]}],
        [{"name": "a", "label": "x", "type": "text", "rows": 3}],
        # bad values for optional keys
        [{"name": "a", "label": "x", "type": "text", "max_length": 0}],
        [{"name": "a", "label": "x", "type": "text", "max_length": 501}],
        [{"name": "a", "label": "x", "type": "textarea", "rows": 1}],
        [{"name": "a", "label": "x", "type": "integer", "min": 1.5}],
        [{"name": "a", "label": "x", "type": "number", "min": 10, "max": 1}],
        [{"name": "a", "label": "x", "type": "number", "min": "1"}],
        [{"name": "a", "label": "x", "type": "text", "help_text": "h" * 501}],
        # choices
        [{"name": "a", "label": "x", "type": "select"}],
        [{"name": "a", "label": "x", "type": "select", "options": []}],
        [{"name": "a", "label": "x", "type": "radio", "options": ["a", "a"]}],
        [{"name": "a", "label": "x", "type": "checkboxes", "options": ["", "b"]}],
        [{"name": "a", "label": "x", "type": "select", "options": [1]}],
        [{"name": "a", "label": "x", "type": "select", "options": [f"o{i}" for i in range(51)]}],
        # layout
        [{"name": "a", "label": "x", "type": "heading", "required": True}],
        [{"name": "a", "label": "x" * 201, "type": "heading"}],
        [{"name": "a", "label": "x", "type": "deadline", "required": True}],
        [
            {"name": "a", "label": "x", "type": "deadline"},
            {"name": "b", "label": "y", "type": "deadline"},
        ],
        [{"name": "a", "label": "x", "type": "link", "url": "not a url"}],
        [{"name": "a", "label": "x", "type": "link", "url": "ftp://x.example"}],
        [{"name": "a", "label": "x", "type": "link", "url": "https://x.example/" + "y" * 500}],
        [{"name": "a", "label": "x", "type": "text", "url": "https://x.example"}],
        # description, word limit, budget
        [{"name": "a", "label": "x", "type": "text", "description": "d" * 301}],
        [{"name": "a", "label": "x", "type": "textarea", "max_words": 0}],
        [{"name": "a", "label": "x", "type": "textarea", "max_words": 5001}],
        [{"name": "a", "label": "x", "type": "text", "max_words": 10}],
        [{"name": "a", "label": "x", "type": "budget", "currency": "NOK"}],
        [{"name": "a", "label": "x", "type": "budget", "max_award": 0}],
        [{"name": "a", "label": "x", "type": "budget", "max_award": "75000"}],
        [{"name": "a", "label": "x", "type": "budget", "max_lines": 31}],
    ],
)
def test_invalid_schemas(schema: Any) -> None:
    with pytest.raises(SchemaError):
        validate_schema(schema)


BUDGET = [
    {"label": "Staff costs", "amount": "42000"},
    {"label": "Equipment", "amount": "12500.5"},
]


def test_parse_budget_reads_lines_and_lists() -> None:
    text = "Staff costs | 42 000\n\nEquipment|12500,50\n"
    assert parse_budget(text) == BUDGET
    assert parse_budget(BUDGET) == BUDGET
    assert parse_budget("Fee | 0") == [{"label": "Fee", "amount": "0"}]


@pytest.mark.parametrize(
    "value",
    [
        "Staff costs 42000",
        "| 42000",
        "Staff | abc",
        "Staff | -1",
        "Staff | 1.234",
        "Staff | 1e15",
        f"{'x' * 201} | 1",
        [{"label": "Staff"}],
        [1],
        42,
    ],
)
def test_parse_budget_rejects(value: Any) -> None:
    with pytest.raises(forms.ValidationError):
        parse_budget(value)


def test_budget_field_round_trip_and_limits() -> None:
    form_class = build_form(EVERY_TYPE[-3:], forms.Form)
    assert list(form_class.base_fields) == ["costs"]
    field = form_class.base_fields["costs"]
    assert field.widget.attrs["data-currency"] == "SEK"
    assert field.widget.attrs["data-max-award"] == "75000"
    form = form_class(data={"costs": "Staff costs | 42000\nEquipment | 12500.50"})
    assert form.is_valid(), form.errors
    answers = answers_to_json(form.cleaned_data)
    assert answers == {"costs": BUDGET}
    # Stored answers validate again, as the org does on receipt, and render back as lines.
    again = form_class(data=answers)
    assert again.is_valid(), again.errors
    assert "Staff costs | 42000\nEquipment | 12500.5" in str(form_class(initial=answers)["costs"])
    over = form_class(data={"costs": "Staff | 70000\nTravel | 5001"})
    assert not over.is_valid() and f"75{THOUSANDS_SEP}000 SEK" in over.errors["costs"][0]
    long = form_class(data={"costs": "A | 1\nB | 1\nC | 1\nD | 1"})
    assert not long.is_valid() and "at most 3 lines" in long.errors["costs"][0]
    assert not form_class(data={"costs": ""}).is_valid()
    optional = build_form([{**EVERY_TYPE[-3], "required": False}], forms.Form)(data={"costs": ""})
    assert optional.is_valid() and optional.cleaned_data["costs"] == []


def test_display_budget() -> None:
    assert display_budget(BUDGET, "SEK").replace(THOUSANDS_SEP, " ") == (
        "Staff costs: 42 000 SEK; Equipment: 12 500.50 SEK; Total: 54 500.50 SEK"
    )
    assert display_budget([], "SEK") == "" and display_budget(None, "SEK") == ""
    assert display_budget("garbage", "SEK") == "garbage"
    shown = dict(labelled_answers(EVERY_TYPE, {"costs": BUDGET}))
    assert shown["Budget breakdown"].startswith(f"Staff costs: 42{THOUSANDS_SEP}000 SEK")
    assert "Application deadline" not in shown and "Funder website" not in shown


def test_require_publishable_needs_link_urls() -> None:
    require_publishable(validate_schema(EVERY_TYPE))
    require_publishable(validate_schema([*BASE_FIELDS, *DEFAULT_FIELDS[:2]]))
    with pytest.raises(SchemaError, match="Funder website"):
        require_publishable(validate_schema([*BASE_FIELDS, *DEFAULT_FIELDS]))


def test_default_fields_validate_and_get_their_names_from_labels() -> None:
    named = assign_names([{k: v for k, v in f.items() if k != "name"} for f in DEFAULT_FIELDS])
    assert isinstance(named, list)
    assert [f["name"] for f in named] == [f["name"] for f in DEFAULT_FIELDS]
    require_base_fields(validate_schema([*BASE_FIELDS, *DEFAULT_FIELDS]))


def test_build_form_validates_required_and_types() -> None:
    form_class = build_form(SCHEMA, forms.Form)
    assert list(form_class.base_fields) == ["title", "summary", "budget", "start"]
    form = form_class(data={"title": "", "budget": "abc"})
    assert not form.is_valid()
    assert set(form.errors) == {"title", "budget"}
    form = form_class(data={"title": "Solar", "budget": "1500", "start": "2027-02-01"})
    assert form.is_valid(), form.errors
    answers = answers_to_json(form.cleaned_data)
    assert answers == {"title": "Solar", "summary": "", "budget": "1500", "start": "2027-02-01"}


def test_build_form_with_every_type() -> None:
    form_class = build_form(EVERY_TYPE, forms.Form)
    assert "about" not in form_class.base_fields and "intro" not in form_class.base_fields
    assert isinstance(form_class.base_fields["size"].widget, forms.RadioSelect)
    assert form_class.base_fields["full_name"].widget.attrs["placeholder"] == "Jane Doe"
    assert form_class.base_fields["bio"].widget.attrs["rows"] == 3
    assert form_class.base_fields["full_name"].help_text == "As in your passport."
    data = {
        "full_name": "Jane",
        "email": "jane@example.org",
        "site": "example.org",
        "phone": "+46 8 123",
        "budget": "12.50",
        "years": "3",
        "start": "2027-01-02",
        "at": "09:30",
        "kickoff": "2027-01-02T09:30",
        "area": "Water",
        "size": "Large",
        "topics": ["AI", "Sea"],
        "agree": "on",
        "org": "kth",
        "costs": "Staff | 100",
    }
    form = form_class(data=data)
    assert form.is_valid(), form.errors
    answers = answers_to_json(form.cleaned_data)
    assert answers["site"] == "https://example.org"
    assert answers["costs"] == [{"label": "Staff", "amount": "100"}]
    assert answers["budget"] == "12.50" and answers["years"] == 3
    assert answers["at"] == "09:30:00" and answers["kickoff"].startswith("2027-01-02T09:30")
    assert answers["topics"] == ["AI", "Sea"] and answers["agree"] is True
    assert answers["area"] == "Water"
    # The stored answers validate again, as the org does on receipt.
    again = form_class(data=answers)
    assert again.is_valid(), again.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("site", "not a url"),
        ("years", "6"),
        ("years", "2.5"),
        ("budget", "-1"),
        ("area", "Fire"),
        ("size", "Medium"),
        ("topics", ["AI", "Fire"]),
        ("topics", "AI"),
        ("agree", ""),
        ("full_name", "x" * 101),
        ("at", "25:00"),
        ("org", "nowhere"),
        ("costs", "Staff | 80000"),
        ("costs", "no amount"),
    ],
)
def test_build_form_rejects_bad_values(field: str, value: Any) -> None:
    form_class = build_form(EVERY_TYPE, forms.Form)
    data: dict[str, Any] = {
        "full_name": "Jane",
        "email": "jane@example.org",
        "years": "3",
        "size": "Small",
        "agree": "on",
        "org": "kth",
        "costs": "Staff | 100",
        field: value,
    }
    form = form_class(data=data)
    assert not form.is_valid()
    assert field in form.errors, form.errors


def test_optional_select_gets_a_blank_choice_and_required_does_not() -> None:
    optional = str(build_form(EVERY_TYPE, forms.Form)()["area"])
    assert '<option value="" selected>---------</option>' in optional
    required = validate_schema([{**EVERY_TYPE[12], "required": True}])
    assert '<option value="">' not in str(build_form(required, forms.Form)()["area"])


def test_answers_to_json_types() -> None:
    assert answers_to_json(
        {
            "d": date(2027, 1, 2),
            "n": Decimal("12.50"),
            "t": time(9, 30),
            "dt": datetime(2027, 1, 2, 9, 30),
            "l": ["a"],
            "b": False,
            "i": 3,
        }
    ) == {
        "d": "2027-01-02",
        "n": "12.50",
        "t": "09:30:00",
        "dt": "2027-01-02T09:30:00",
        "l": ["a"],
        "b": False,
        "i": 3,
    }


def test_labelled_answers_follow_schema_order_and_format_values() -> None:
    assert labelled_answers(SCHEMA[:2], {"summary": "s", "title": "t"}) == [
        ("Title", "t"),
        ("Summary", "s"),
    ]
    shown = dict(labelled_answers(EVERY_TYPE, {"topics": ["AI", "Sea"], "agree": True, "years": 3}))
    assert "About you" not in shown and "Tell us who you are." not in shown
    assert shown["Topics"] == "AI, Sea" and shown["I agree"] == "Yes" and shown["Years"] == "3"
    assert shown["Bio"] == ""


def test_form_layout_interleaves_layout_entries_and_fields() -> None:
    form = build_form(EVERY_TYPE, forms.Form)()
    rows = form_layout(EVERY_TYPE, form)
    assert [r["spec"]["name"] for r in rows] == [s["name"] for s in EVERY_TYPE]
    assert rows[0]["field"] is None and rows[1]["field"] is None
    assert rows[2]["field"] is not None and rows[2]["field"].name == "full_name"
    assert rows[-1]["field"] is None and rows[-2]["field"] is None  # link, deadline
    assert rows[-3]["field"] is not None and rows[-3]["field"].name == "costs"


def test_require_base_fields() -> None:
    require_base_fields(validate_schema([*BASE_FIELDS, *SCHEMA]))
    require_base_fields(validate_schema([*SCHEMA, *reversed(BASE_FIELDS)]))
    with pytest.raises(SchemaError, match="applicant_name"):
        require_base_fields(validate_schema(SCHEMA))
    with pytest.raises(SchemaError, match="applicant_email"):
        require_base_fields(validate_schema([BASE_FIELDS[0]]))
    not_required = [BASE_FIELDS[0], {**BASE_FIELDS[1], "required": False}]
    with pytest.raises(SchemaError, match="applicant_email"):
        require_base_fields(validate_schema(not_required))
    wrong_type = [{**BASE_FIELDS[0], "type": "textarea"}, BASE_FIELDS[1]]
    with pytest.raises(SchemaError, match="applicant_name"):
        require_base_fields(validate_schema(wrong_type))


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("Budget (SEK)", "budget_sek"),
        ("  Project   title ", "project_title"),
        ("Oskar Bergström's årsplan", "oskar_bergstrom_s_arsplan"),
        ("Smørrebrød", "smrrebrd"),
        ("2027 plans", "f_2027_plans"),
        ("Documents", "f_documents"),
        ("", "field"),
        ("???", "field"),
        ("x" * 60, "x" * 40),
    ],
)
def test_field_name_is_derived_from_the_label(label: str, name: str) -> None:
    assert field_name(label) == name
    validate_schema([{"name": name, "label": label or "x", "type": "text"}])


def test_assign_names_ignores_user_names_and_keeps_base_fields() -> None:
    schema = [
        {"name": "DROP TABLE", "label": "Budget (SEK)", "type": "number"},
        {"name": "applicant_email", "label": "Email", "type": "email", "required": True},
        {"name": "whatever", "label": "Budget (SEK)", "type": "text"},
        {"label": "Applicant name", "type": "text"},
        {"name": "applicant_name", "label": "Name", "type": "text", "required": True},
        {"name": "applicant_name", "label": "Name again", "type": "text"},
        {"name": "x" * 40, "label": "y" * 40, "type": "text"},
        {"name": "y" * 40, "label": "y" * 40, "type": "text"},
    ]
    named = assign_names(schema)
    assert isinstance(named, list)
    assert [f["name"] for f in named] == [
        "budget_sek",
        "applicant_email",
        "budget_sek_2",
        "applicant_name_2",
        "applicant_name",
        "name_again",
        "y" * 40,
        "y" * 38 + "_2",
    ]
    assert schema[0]["name"] == "DROP TABLE"  # the input is not modified
    validate_schema(named)
    assert assign_names("nope") == "nope" and assign_names([1]) == [1]


def test_required_yes_no_accepts_no_but_requires_an_answer() -> None:
    form_type = build_form(
        [{"name": "human", "label": "Human participants?", "type": "checkbox", "required": True}],
        forms.Form,
    )
    for answer, expected in [("False", False), (False, False), ("True", True), ("on", True)]:
        form = form_type({"human": answer})
        assert form.is_valid(), form.errors
        assert form.cleaned_data["human"] is expected
    assert not form_type({}).is_valid()
    assert not form_type({"human": "maybe"}).is_valid()
    assert list(form_type(initial={"human": False})["human"])[1].data["selected"]
