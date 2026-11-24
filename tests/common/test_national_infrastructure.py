"""Regression coverage for the compound VR infrastructure question."""

import pytest
from django import forms
from django.http import QueryDict

from it42.common.formschema import answers_to_json, build_form, labelled_answers
from it42.common.infrastructure import NAMES, OTHER

SCHEMA = [
    {
        "name": "facilities",
        "label": "National Infrastructure",
        "type": "national_infrastructure",
        "required": True,
    }
]


def test_directory_is_sorted_and_other_is_last() -> None:
    """Every supplied name appears in alphabetical order in the dropdown."""
    assert len(set(NAMES)) == len(NAMES) == 84
    widget = str(build_form(SCHEMA, forms.Form)()["facilities"])
    assert [widget.index(f'value="{name}"') for name in sorted(NAMES, key=str.casefold)] == sorted(
        widget.index(f'value="{name}"') for name in NAMES
    )
    assert widget.index(f'value="{OTHER}"') > widget.index(f'value="{NAMES[-1]}"')


@pytest.mark.parametrize(
    ("selected", "other"),
    [([NAMES[0], NAMES[-1]], ""), ([], "Unlisted"), ([NAMES[0], OTHER], "Unlisted")],
)
def test_yes_survives_submission_and_org_revalidation(selected: list[str], other: str) -> None:
    """Applicant POSTs and the JSON payload validated by the org describe the same answer."""
    data = QueryDict(mutable=True)
    data["facilities.use"] = "yes"
    data.setlist("facilities.selected", selected)
    data["facilities.other"] = other
    form_class = build_form(SCHEMA, forms.Form)
    form = form_class(data)
    assert form.is_valid(), form.errors
    payload = answers_to_json(form.cleaned_data)
    received = form_class(payload)
    assert received.is_valid() and received.cleaned_data == payload
    [(label, display)] = labelled_answers(SCHEMA, payload)
    assert label == "National Infrastructure"
    assert display.splitlines() == [
        "Yes",
        *(s for s in selected if s != OTHER),
        *other.splitlines(),
    ]


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {"use": "yes", "selected": [], "other": " "},
        {"use": "yes", "selected": [OTHER], "other": ""},
        {"use": "yes", "selected": ["Unknown"], "other": "Extra"},
        {"use": "yes", "selected": "CeXS", "other": ""},
        {"use": "no", "other": "Stale value"},
        {"use": "maybe"},
    ],
)
def test_invalid_infrastructure_answers_are_rejected(answer: object) -> None:
    """Reject missing, inconsistent, or unlisted structured answers at submission."""
    assert not build_form(SCHEMA, forms.Form)({"facilities": answer}).is_valid()


def test_no_clears_details_and_optional_can_be_skipped() -> None:
    """An explicit No and an unanswered optional question remain distinct."""
    posted = QueryDict("facilities.use=no&facilities.selected=CeXS&facilities.other=Extra")
    form = build_form(SCHEMA, forms.Form)(posted)
    assert form.is_valid()
    assert form.cleaned_data["facilities"] == {"use": "no"}
    assert labelled_answers(SCHEMA, form.cleaned_data)[0][1] == "No"

    optional = build_form([{**SCHEMA[0], "required": False}], forms.Form)(QueryDict(""))
    assert optional.is_valid() and optional.cleaned_data["facilities"] is None
