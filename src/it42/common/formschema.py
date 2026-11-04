"""Grant application forms described as JSON.

A schema is a list of fields::

    [{"name": "budget", "label": "Budget (SEK)", "type": "number", "required": true}]

Every entry has ``name``, ``label``, ``type`` and ``required`` and may have ``help_text``.
Each type allows a few extra keys (see ``WIDGETS``). ``heading`` and ``paragraph`` are
layout entries: they are shown on the form but have no answer. Documents are attached
separately, so there is no file type.

Every form built with the org's builder keeps three base fields (``BASE_FIELDS``): the
applicant's name and email address, and the administrating organisation (type
``research_org``, a choice from the research organisation directory) that has to sign the
application before the org reviews it. The org may make that one optional: an empty answer
means no sign-off. ``require_base_fields`` checks all three.

Field names are never typed by users: ``assign_names`` derives them from the labels
(the builder shows the result, the org derives them again when a draft is saved).
"""

import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django import forms

from . import research_orgs

MAX_FIELDS = 30
MAX_OPTIONS = 50
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RESERVED_NAMES = {"documents", "csrfmiddlewaretoken"}

# type -> (palette label, palette group, extra keys the type accepts)
WIDGETS: dict[str, dict[str, Any]] = {
    "text": {"label": "Short text", "group": "Text", "keys": ("placeholder", "max_length")},
    "textarea": {
        "label": "Long text",
        "group": "Text",
        "keys": ("placeholder", "max_length", "rows"),
    },
    "email": {"label": "Email address", "group": "Text", "keys": ("placeholder",)},
    "url": {"label": "Web address", "group": "Text", "keys": ("placeholder",)},
    "tel": {"label": "Phone number", "group": "Text", "keys": ("placeholder",)},
    "number": {"label": "Number (decimal)", "group": "Numbers", "keys": ("min", "max")},
    "integer": {"label": "Whole number", "group": "Numbers", "keys": ("min", "max")},
    "date": {"label": "Date", "group": "Dates", "keys": ()},
    "time": {"label": "Time", "group": "Dates", "keys": ()},
    "datetime": {"label": "Date and time", "group": "Dates", "keys": ()},
    "select": {"label": "Dropdown", "group": "Choices", "keys": ("options",)},
    "radio": {"label": "Radio buttons", "group": "Choices", "keys": ("options",)},
    "checkboxes": {"label": "Checkbox group", "group": "Choices", "keys": ("options",)},
    "checkbox": {"label": "Yes / no checkbox", "group": "Choices", "keys": ()},
    # Only as the administrating_organisation base field, so not on the builder's palette.
    "research_org": {
        "label": "Administrating organisation",
        "group": "Choices",
        "keys": (),
        "palette": False,
    },
    "heading": {"label": "Section heading", "group": "Layout", "keys": ()},
    "paragraph": {"label": "Explanatory text", "group": "Layout", "keys": ()},
}
FIELD_TYPES = tuple(WIDGETS)
LAYOUT_TYPES = ("heading", "paragraph")
CHOICE_TYPES = ("select", "radio", "checkboxes")
COMMON_KEYS = ("name", "label", "type", "required", "help_text")
MAX_LENGTH_LIMIT = {"text": 500, "textarea": 10_000}

ADMIN_ORG_FIELD = "administrating_organisation"
BASE_FIELDS: list[dict[str, Any]] = [
    {"name": "applicant_name", "label": "Your name", "type": "text", "required": True},
    {"name": "applicant_email", "label": "Email address", "type": "email", "required": True},
    {
        "name": ADMIN_ORG_FIELD,
        "label": "Administrating organisation",
        "type": "research_org",
        "required": True,
        "help_text": (
            "The university or research institute that will administer the grant. "
            "It signs your application before the funder reviews it."
        ),
    },
]
BASE_FIELD_NAMES = tuple(f["name"] for f in BASE_FIELDS)
# Base fields the org may make optional (the others must stay required).
OPTIONAL_BASE_FIELDS = (ADMIN_ORG_FIELD,)


class SchemaError(ValueError):
    pass


def _check_text(raw: dict[str, Any], key: str, index: int, max_length: int) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise SchemaError(f"Field {index}: {key} must be a string of at most {max_length}.")
    return value.strip() or None


def _check_int(raw: dict[str, Any], key: str, index: int, low: int, high: int) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise SchemaError(f"Field {index}: {key} must be a whole number from {low} to {high}.")
    return value


def _check_bound(raw: dict[str, Any], key: str, index: int, field_type: str) -> int | float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SchemaError(f"Field {index}: {key} must be a number.")
    if field_type == "integer" and not isinstance(value, int):
        raise SchemaError(f"Field {index}: {key} must be a whole number.")
    return value


def _check_options(raw: dict[str, Any], index: int) -> list[str]:
    options = raw.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
        raise SchemaError(f"Field {index}: options must be a list of 1-{MAX_OPTIONS} choices.")
    cleaned: list[str] = []
    for option in options:
        if not isinstance(option, str) or not option.strip() or len(option) > 200:
            raise SchemaError(f"Field {index}: each option must be 1-200 characters.")
        if option.strip() in cleaned:
            raise SchemaError(f"Field {index}: the option {option.strip()!r} is listed twice.")
        cleaned.append(option.strip())
    return cleaned


def validate_schema(schema: object) -> list[dict[str, Any]]:
    """Return a normalised copy of ``schema`` or raise SchemaError."""
    if not isinstance(schema, list):
        raise SchemaError("The form schema must be a JSON list of fields.")
    if len(schema) > MAX_FIELDS:
        raise SchemaError(f"A form can have at most {MAX_FIELDS} fields.")
    seen: set[str] = set()
    fields = []
    org_fields = 0
    for index, raw in enumerate(schema, start=1):
        if not isinstance(raw, dict):
            raise SchemaError(f"Field {index} must be an object.")
        field_type = raw.get("type", "text")
        if field_type not in FIELD_TYPES:
            raise SchemaError(f"Field {index}: type must be one of {', '.join(FIELD_TYPES)}.")
        allowed = set(COMMON_KEYS) | set(WIDGETS[field_type]["keys"])
        unknown = set(raw) - allowed
        if unknown:
            raise SchemaError(f"Field {index} has unknown keys: {', '.join(sorted(unknown))}.")
        name, label = raw.get("name"), raw.get("label")
        required = raw.get("required", False)
        if not isinstance(name, str) or not NAME_RE.match(name) or name in RESERVED_NAMES:
            raise SchemaError(
                f"Field {index}: name must be lowercase letters, digits and underscores, "
                "starting with a letter (max 40 characters)."
            )
        if name in seen:
            raise SchemaError(f"Field {index}: the name {name!r} is used twice.")
        label_limit = 2000 if field_type == "paragraph" else 200
        if not isinstance(label, str) or not label.strip() or len(label) > label_limit:
            raise SchemaError(f"Field {index}: label must be 1-{label_limit} characters.")
        if not isinstance(required, bool):
            raise SchemaError(f"Field {index}: required must be true or false.")
        if field_type in LAYOUT_TYPES and required:
            raise SchemaError(f"Field {index}: a {field_type} cannot be required.")
        if field_type == "research_org":
            org_fields += 1
            if org_fields > 1:
                raise SchemaError("A form can ask for the administrating organisation once.")
        seen.add(name)
        spec: dict[str, Any] = {
            "name": name,
            "label": label.strip(),
            "type": field_type,
            "required": required,
        }
        if help_text := _check_text(raw, "help_text", index, 500):
            spec["help_text"] = help_text
        if placeholder := _check_text(raw, "placeholder", index, 200):
            spec["placeholder"] = placeholder
        if field_type in MAX_LENGTH_LIMIT and (
            max_length := _check_int(raw, "max_length", index, 1, MAX_LENGTH_LIMIT[field_type])
        ):
            spec["max_length"] = max_length
        if field_type == "textarea" and (rows := _check_int(raw, "rows", index, 2, 20)):
            spec["rows"] = rows
        if field_type in ("number", "integer"):
            low = _check_bound(raw, "min", index, field_type)
            high = _check_bound(raw, "max", index, field_type)
            if low is not None and high is not None and low > high:
                raise SchemaError(f"Field {index}: min must not be larger than max.")
            if low is not None:
                spec["min"] = low
            if high is not None:
                spec["max"] = high
        if field_type in CHOICE_TYPES:
            spec["options"] = _check_options(raw, index)
        fields.append(spec)
    return fields


def field_name(label: str) -> str:
    """The key an answer is stored under, derived from the field's label."""
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")
    if not name:
        return "field"
    if not name[0].isalpha() or name in RESERVED_NAMES:
        name = f"f_{name}"
    return name[:40]


def assign_names(schema: object) -> object:
    """Return ``schema`` with every entry named after its label, unique in order.

    Base fields keep their fixed names (a ``research_org`` entry is always the
    administrating organisation); nothing else may use them. Anything that is not a list
    of objects is returned as is, for ``validate_schema`` to report.
    """
    if not isinstance(schema, list):
        return schema
    taken: set[str] = set()
    out: list[Any] = []
    for raw in schema:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        entry = dict(raw)
        given = entry.get("name")
        name = given if isinstance(given, str) and given in BASE_FIELD_NAMES else ""
        if entry.get("type") == "research_org":
            # The only use of the type is the administrating_organisation base field.
            name = ADMIN_ORG_FIELD
        if not name or name in taken:
            label = entry.get("label")
            base = field_name(label if isinstance(label, str) else "")
            name, n = base, 2
            while name in taken or name in BASE_FIELD_NAMES:
                suffix = f"_{n}"
                name, n = base[: 40 - len(suffix)] + suffix, n + 1
        taken.add(name)
        entry["name"] = name
        out.append(entry)
    return out


def require_base_fields(schema: list[dict[str, Any]]) -> None:
    """Every grant form keeps the applicant's name and email and the administrating
    organisation (``BASE_FIELDS``); only the last may be optional."""
    by_name = {spec["name"]: spec for spec in schema}
    for base in BASE_FIELDS:
        spec = by_name.get(base["name"])
        if spec is None:
            raise SchemaError(f"The form must keep the {base['name']} field.")
        if spec["type"] != base["type"]:
            raise SchemaError(f"The {base['name']} field must be a {base['type']} field.")
        if not spec["required"] and base["name"] not in OPTIONAL_BASE_FIELDS:
            raise SchemaError(f"The {base['name']} field must be a required {base['type']} field.")


def research_org_of(schema: list[dict[str, Any]], answers: dict[str, Any]) -> str:
    """The administrating organisation's slug chosen in ``answers``, or "" for none."""
    for spec in schema:
        if spec.get("type") == "research_org":
            value = answers.get(spec["name"])
            return value if isinstance(value, str) else ""
    return ""


def is_layout(spec: dict[str, Any]) -> bool:
    return spec["type"] in LAYOUT_TYPES


def _form_field(spec: dict[str, Any]) -> forms.Field:
    common: dict[str, Any] = {
        "label": spec["label"],
        "required": spec["required"],
        "help_text": spec.get("help_text", ""),
    }
    attrs: dict[str, Any] = {}
    if placeholder := spec.get("placeholder"):
        attrs["placeholder"] = placeholder
    choices = [(option, option) for option in spec.get("options", [])]
    match spec["type"]:
        case "textarea":
            attrs["rows"] = spec.get("rows", 5)
            return forms.CharField(
                max_length=spec.get("max_length", 10_000),
                widget=forms.Textarea(attrs=attrs),
                **common,
            )
        case "email":
            return forms.EmailField(max_length=254, widget=forms.EmailInput(attrs=attrs), **common)
        case "url":
            return forms.URLField(
                max_length=500, assume_scheme="https", widget=forms.URLInput(attrs=attrs), **common
            )
        case "tel":
            return forms.CharField(
                max_length=50, widget=forms.TextInput(attrs={"type": "tel", **attrs}), **common
            )
        case "number":
            return forms.DecimalField(
                max_digits=15,
                decimal_places=2,
                min_value=spec.get("min"),
                max_value=spec.get("max"),
                **common,
            )
        case "integer":
            return forms.IntegerField(
                min_value=spec.get("min"), max_value=spec.get("max"), **common
            )
        case "date":
            return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **common)
        case "time":
            return forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}), **common)
        case "datetime":
            return forms.DateTimeField(
                widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), **common
            )
        case "select":
            if not spec["required"]:
                choices.insert(0, ("", "---------"))
            return forms.ChoiceField(choices=choices, **common)
        case "radio":
            return forms.ChoiceField(choices=choices, widget=forms.RadioSelect, **common)
        case "checkboxes":
            return forms.MultipleChoiceField(
                choices=choices, widget=forms.CheckboxSelectMultiple, **common
            )
        case "checkbox":
            return forms.BooleanField(**common)
        case "research_org":
            orgs = research_orgs.choices()
            if not spec["required"]:
                orgs.insert(0, ("", "None"))
            else:
                orgs.insert(0, ("", "Choose an organisation"))
            return forms.ChoiceField(
                choices=orgs,
                # static/it42/combobox.js turns it into a type-to-search box.
                widget=forms.Select(attrs={"data-combobox": "true"}),
                **common,
            )
        case _:
            return forms.CharField(
                max_length=spec.get("max_length", 500),
                widget=forms.TextInput(attrs=attrs),
                **common,
            )


def build_form[F: forms.Form](schema: list[dict[str, Any]], base: type[F]) -> type[F]:
    """A subclass of ``base`` with one field per input entry of the schema, in order."""
    fields: dict[str, Any] = {
        spec["name"]: _form_field(spec) for spec in validate_schema(schema) if not is_layout(spec)
    }
    form_class: Any = type("GrantApplicationForm", (base,), fields)
    return form_class


def form_layout(schema: list[dict[str, Any]], form: forms.BaseForm) -> list[dict[str, Any]]:
    """Rows to render, in schema order: ``{"spec": ..., "field": BoundField | None}``."""
    return [
        {"spec": spec, "field": None if is_layout(spec) else form[spec["name"]]}
        for spec in schema
        if is_layout(spec) or spec["name"] in form.fields
    ]


def answers_to_json(cleaned_data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in cleaned_data.items():
        if isinstance(value, datetime | date | time):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = (
                format(value.normalize(), "f") if value == value.to_integral() else str(value)
            )
        else:
            out[key] = value
    return out


def display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def labelled_answers(
    schema: list[dict[str, Any]], answers: dict[str, Any]
) -> list[tuple[str, str]]:
    """(label, value) pairs in schema order, for display. Layout entries are skipped;
    organisations are shown by name."""
    out = []
    for spec in schema:
        if is_layout(spec):
            continue
        value = answers.get(spec["name"])
        if spec["type"] == "research_org":
            out.append((spec["label"], research_orgs.name_of(value) if value else "None"))
        else:
            out.append((spec["label"], display_value(value)))
    return out
