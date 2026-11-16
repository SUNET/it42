"""Grant application forms described as JSON.

A schema is a list of fields::

    [{"name": "budget", "label": "Budget (SEK)", "type": "number", "required": true}]

Every entry has ``name``, ``label``, ``type`` and ``required`` and may have ``help_text``
(guidance shown in a box under the question) and ``description`` (a secondary line under
the label). Each type allows a few extra keys (see ``WIDGETS``). ``heading``, ``paragraph``,
``deadline`` and ``link`` are layout entries (``LAYOUT_TYPES``): they are shown on the form
but have no answer. A ``deadline`` shows the grant's own closing date and time (at most one
per form); a ``link`` holds a web address the funder sets (``url``, which a draft may leave
empty: ``require_publishable`` refuses to publish without it). A ``budget`` is answered with
a list of lines, ``[{"label": ..., "amount": "decimal"}]``, whose total may not exceed the
field's ``max_award``. Documents are attached separately, so there is no file type.

Every form built with the org's builder keeps three base fields (``BASE_FIELDS``): the
applicant's name and email address, and the administrating organisation (type
``research_org``, a choice from the research organisation directory) that has to sign the
application before the org reviews it. The org may make that one optional: an empty answer
means no sign-off. ``require_base_fields`` checks all three. A new form also starts with
``DEFAULT_FIELDS`` (grant summary, application deadline, funder website), which the org may
remove or change; the builder marks them "Default" by name.

Field names are never typed by users: ``assign_names`` derives them from the labels
(the builder shows the result, the org derives them again when a draft is saved).
"""

import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from . import research_orgs

MAX_FIELDS = 30
MAX_OPTIONS = 50
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RESERVED_NAMES = {"documents", "csrfmiddlewaretoken"}

# type -> palette label, hint and Phosphor icon, palette group (in palette order), extra
# keys the type accepts. ``palette: False`` keeps a type valid but off the builder's palette.
WIDGETS: dict[str, dict[str, Any]] = {
    "text": {
        "label": "Short text",
        "hint": "A line or two, like a title",
        "icon": "text-t",
        "group": "Text",
        "keys": ("placeholder", "max_length"),
    },
    "textarea": {
        "label": "Long text",
        "hint": "Paragraphs, with a word limit",
        "icon": "text-align-left",
        "group": "Text",
        "keys": ("placeholder", "max_length", "max_words", "rows"),
    },
    "email": {
        "label": "Email",
        "hint": "Checked for a valid address",
        "icon": "envelope-simple",
        "group": "Text",
        "keys": ("placeholder",),
    },
    "tel": {
        "label": "Phone",
        "hint": "With country code",
        "icon": "phone",
        "group": "Text",
        "keys": ("placeholder",),
    },
    # Applicant-typed web addresses stay valid in older forms; the palette offers the
    # funder-set "External link" block instead.
    "url": {
        "label": "Web address",
        "hint": "A web address the applicant types",
        "icon": "link",
        "group": "Text",
        "keys": ("placeholder",),
        "palette": False,
    },
    "number": {
        "label": "Decimal",
        "hint": "Amounts with decimals, like 12.50",
        "icon": "hash",
        "group": "Numbers",
        "keys": ("min", "max"),
    },
    "integer": {
        "label": "Whole number",
        "hint": "Counts, like team size",
        "icon": "number-square-one",
        "group": "Numbers",
        "keys": ("min", "max"),
    },
    "date": {
        "label": "Date",
        "hint": "Day, month and year",
        "icon": "calendar-blank",
        "group": "Dates",
        "keys": (),
    },
    "time": {
        "label": "Time",
        "hint": "Hours and minutes",
        "icon": "clock",
        "group": "Dates",
        "keys": (),
    },
    "datetime": {
        "label": "Date and time",
        "hint": "A date with a time",
        "icon": "calendar-check",
        "group": "Dates",
        "keys": (),
    },
    "select": {
        "label": "Dropdown",
        "hint": "Pick one from a list",
        "icon": "caret-up-down",
        "group": "Choices",
        "keys": ("options",),
    },
    "radio": {
        "label": "Radio buttons",
        "hint": "Pick one, all options shown",
        "icon": "radio-button",
        "group": "Choices",
        "keys": ("options",),
    },
    "checkboxes": {
        "label": "Checkboxes",
        "hint": "Pick any that apply",
        "icon": "check-square",
        "group": "Choices",
        "keys": ("options",),
    },
    "checkbox": {
        "label": "Yes / no",
        "hint": "A single yes or no answer",
        "icon": "toggle-left",
        "group": "Choices",
        "keys": (),
    },
    # Only as the administrating_organisation base field, so not on the builder's palette.
    "research_org": {
        "label": "Administrating organisation",
        "hint": "A research organisation from the directory",
        "icon": "buildings",
        "group": "Choices",
        "keys": (),
        "palette": False,
    },
    "budget": {
        "label": "Budget",
        "hint": "Line items with a total and max award",
        "icon": "coins",
        "group": "Grant",
        "keys": ("currency", "max_award", "max_lines"),
    },
    "deadline": {
        "label": "Deadline",
        "hint": "Date and time applications close",
        "icon": "calendar-check",
        "group": "Grant",
        "keys": (),
    },
    "link": {
        "label": "External link",
        "hint": "A web address applicants can open",
        "icon": "link",
        "group": "Grant",
        "keys": ("url",),
    },
    "heading": {
        "label": "Section heading",
        "hint": "Starts a new part of the form",
        "icon": "text-h",
        "group": "Sections",
        "keys": (),
    },
    "paragraph": {
        "label": "Explanation text",
        "hint": "Guidance shown to applicants",
        "icon": "paragraph",
        "group": "Sections",
        "keys": (),
    },
}
FIELD_TYPES = tuple(WIDGETS)
# Shown on the form, but with no answer.
LAYOUT_TYPES = ("heading", "paragraph", "deadline", "link")
CHOICE_TYPES = ("select", "radio", "checkboxes")
COMMON_KEYS = ("name", "label", "type", "required", "help_text", "description")
MAX_LENGTH_LIMIT = {"text": 500, "textarea": 10_000}
MAX_WORDS_LIMIT = 5000
CURRENCIES = ("SEK", "EUR", "GBP", "USD")
MAX_AWARD_LIMIT = 1_000_000_000_000
MAX_BUDGET_LINES = 30
DEFAULT_BUDGET_LINES = 20
_url_validator = URLValidator(schemes=["http", "https"])

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
# Added to every new form after the base fields. The org may edit or remove them; the
# builder badges them "Default" by name (so a renamed one loses the badge).
DEFAULT_FIELDS: list[dict[str, Any]] = [
    {
        "name": "grant_summary",
        "label": "Grant summary",
        "type": "text",
        "required": True,
        "description": "One or two sentences on what the project will do",
        "max_length": 300,
    },
    {
        "name": "application_deadline",
        "label": "Application deadline",
        "type": "deadline",
        "required": False,
        "description": "Applications close at this time",
    },
    {
        "name": "funder_website",
        "label": "Funder website",
        "type": "link",
        "required": False,
        "description": "Where applicants can read the full call",
    },
]
DEFAULT_FIELD_NAMES = tuple(f["name"] for f in DEFAULT_FIELDS)


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
    org_fields = deadlines = 0
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
        if field_type == "deadline":
            deadlines += 1
            if deadlines > 1:
                raise SchemaError("A form can show the application deadline once.")
        seen.add(name)
        spec: dict[str, Any] = {
            "name": name,
            "label": label.strip(),
            "type": field_type,
            "required": required,
        }
        if help_text := _check_text(raw, "help_text", index, 500):
            spec["help_text"] = help_text
        if description := _check_text(raw, "description", index, 300):
            spec["description"] = description
        if placeholder := _check_text(raw, "placeholder", index, 200):
            spec["placeholder"] = placeholder
        if field_type in MAX_LENGTH_LIMIT and (
            max_length := _check_int(raw, "max_length", index, 1, MAX_LENGTH_LIMIT[field_type])
        ):
            spec["max_length"] = max_length
        if field_type == "textarea":
            if rows := _check_int(raw, "rows", index, 2, 20):
                spec["rows"] = rows
            if max_words := _check_int(raw, "max_words", index, 1, MAX_WORDS_LIMIT):
                spec["max_words"] = max_words
        if field_type == "budget":
            currency = raw.get("currency", "SEK")
            if currency not in CURRENCIES:
                raise SchemaError(
                    f"Field {index}: currency must be one of {', '.join(CURRENCIES)}."
                )
            spec["currency"] = currency
            if max_award := _check_int(raw, "max_award", index, 1, MAX_AWARD_LIMIT):
                spec["max_award"] = max_award
            if max_lines := _check_int(raw, "max_lines", index, 1, MAX_BUDGET_LINES):
                spec["max_lines"] = max_lines
        if field_type == "link" and (url := _check_text(raw, "url", index, 500)):
            try:
                _url_validator(url)
            except ValidationError:
                raise SchemaError(f"Field {index}: url must be a web address.") from None
            spec["url"] = url
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


def require_publishable(schema: list[dict[str, Any]]) -> None:
    """What a draft may leave unfinished but a published form may not: every link block
    needs its web address."""
    for spec in schema:
        if spec["type"] == "link" and not spec.get("url"):
            raise SchemaError(f"The {spec['label']} link needs a web address before publishing.")


def research_org_of(schema: list[dict[str, Any]], answers: dict[str, Any]) -> str:
    """The administrating organisation's slug chosen in ``answers``, or "" for none."""
    for spec in schema:
        if spec.get("type") == "research_org":
            value = answers.get(spec["name"])
            return value if isinstance(value, str) else ""
    return ""


def is_layout(spec: dict[str, Any]) -> bool:
    return spec["type"] in LAYOUT_TYPES


class MaxWordsValidator:
    """Refuses a long-text answer with more than ``max_words`` words (a ``textarea``
    field's ``max_words`` key). Words are whitespace-separated runs, as ``str.split``
    counts them, so "e-mail" is one word and "1,500" is one word."""

    def __init__(self, max_words: int) -> None:
        self.max_words = max_words

    def __call__(self, value: str) -> None:
        words = len(value.split())
        if words > self.max_words:
            raise ValidationError(
                f"Use at most {self.max_words} words (this has {words}).", code="max_words"
            )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MaxWordsValidator) and other.max_words == self.max_words


# Thousands separator in shown amounts: a narrow no-break space, so "42 000" never wraps.
THOUSANDS_SEP = "\u202f"


def format_amount(amount: str | int | Decimal) -> str:
    """``"42000"`` -> ``"42 000"``, ``"12.5"`` -> ``"12.50"`` (``THOUSANDS_SEP`` between
    thousands; two decimals only when there are any)."""
    value = Decimal(amount)
    text = f"{value:,.0f}" if value == value.to_integral() else f"{value:,.2f}"
    return text.replace(",", THOUSANDS_SEP)


def budget_total(lines: list[dict[str, Any]]) -> Decimal:
    """The sum of the parsed budget lines' amounts (exact decimal arithmetic)."""
    return sum((Decimal(line["amount"]) for line in lines), Decimal(0))


def parse_budget(value: object) -> list[dict[str, str]]:
    """The budget an applicant typed, as answer lines. Accepts the textarea's text (one
    ``label | amount`` per line) or an already parsed list, as stored answers are.
    Raises ``ValidationError`` for anything else."""
    if isinstance(value, list):
        raw_lines = []
        for item in value:
            if not isinstance(item, dict):
                raise ValidationError("Each budget line needs a label and an amount.")
            raw_lines.append((str(item.get("label", "")), str(item.get("amount", ""))))
    elif isinstance(value, str):
        raw_lines = []
        for text in value.splitlines():
            if not text.strip():
                continue
            label, sep, amount = text.rpartition("|")
            if not sep:
                raise ValidationError(
                    f"Write each budget line as 'What it is for | amount', not {text.strip()!r}."
                )
            raw_lines.append((label, amount))
    else:
        raise ValidationError("Enter the budget as lines.")
    lines = []
    for label, amount in raw_lines:
        label = label.strip()
        if not label or len(label) > 200:
            raise ValidationError("Each budget line needs a label of at most 200 characters.")
        digits = re.sub(r"[\s\u00a0\u2009]", "", amount).replace(",", ".")
        try:
            number = Decimal(digits)
        except (ArithmeticError, ValueError):
            raise ValidationError(f"The amount for {label!r} must be a number.") from None
        if not number.is_finite() or number < 0 or number >= MAX_AWARD_LIMIT:
            raise ValidationError(f"The amount for {label!r} must be from 0 to {MAX_AWARD_LIMIT}.")
        if number != number.quantize(Decimal("0.01")):
            raise ValidationError(f"The amount for {label!r} can have at most 2 decimals.")
        lines.append({"label": label, "amount": format(number.normalize(), "f")})
    return lines


class BudgetWidget(forms.Textarea):
    """A textarea with one ``label | amount`` line per budget line; static/it42/budget.js
    shows it as a table with a running total."""

    def format_value(self, value: Any) -> str | None:
        if isinstance(value, list):
            value = "\n".join(f"{line['label']} | {line['amount']}" for line in value)
        return super().format_value(value)


class BudgetField(forms.Field):
    """The form field for a ``budget`` schema entry. Its value is the list of parsed
    lines (``parse_budget``); ``validate`` enforces the field's line limit and, when the
    org set a ``max_award``, that the total stays under it. The widget attributes carry
    the currency and limits for static/it42/budget.js."""

    widget = BudgetWidget

    def __init__(
        self,
        *,
        currency: str,
        max_award: int | None,
        max_lines: int,
        **kwargs: Any,
    ) -> None:
        self.currency, self.max_award, self.max_lines = currency, max_award, max_lines
        super().__init__(**kwargs)
        self.widget.attrs.update(
            {
                "rows": 6,
                "data-budget": "true",
                "data-currency": currency,
                "data-max-award": "" if max_award is None else str(max_award),
                "data-max-lines": str(max_lines),
                "placeholder": "Staff costs | 42000",
            }
        )

    def to_python(self, value: Any) -> list[dict[str, str]]:
        """Lines from the textarea text, or from an already stored answer list (the org
        re-validates received answers with the same form class)."""
        if value in self.empty_values:
            return []
        return parse_budget(value)

    def validate(self, value: list[dict[str, str]]) -> None:
        """Required-ness (an empty list counts as empty), then the line and total limits."""
        super().validate(value)
        if len(value) > self.max_lines:
            raise ValidationError(f"A budget can have at most {self.max_lines} lines.")
        if self.max_award is not None and budget_total(value) > self.max_award:
            raise ValidationError(
                f"The total may not be more than {format_amount(self.max_award)} {self.currency}."
            )


class YesNoField(forms.TypedChoiceField):
    """An explicit answer; required means either Yes or No must be selected."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            choices=[("True", "Yes"), ("False", "No")],
            coerce=lambda value: value == "True",
            empty_value=None,
            widget=forms.RadioSelect,
            **kwargs,
        )

    def to_python(self, value: Any) -> str:
        # Keep stored boolean answers and older checkbox submissions readable.
        if value is True or value in ("on", "true"):
            value = "True"
        elif value is False or value == "false":
            value = "False"
        return super().to_python(value)


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
            validators = [MaxWordsValidator(spec["max_words"])] if "max_words" in spec else []
            if "max_words" in spec:
                attrs["data-max-words"] = spec["max_words"]  # static/it42/wordcount.js
            return forms.CharField(
                max_length=spec.get("max_length", 10_000),
                widget=forms.Textarea(attrs=attrs),
                validators=validators,
                **common,
            )
        case "budget":
            return BudgetField(
                currency=spec["currency"],
                max_award=spec.get("max_award"),
                max_lines=spec.get("max_lines", DEFAULT_BUDGET_LINES),
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
            return YesNoField(**common)
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


def display_budget(lines: object, currency: str) -> str:
    """``"Staff costs: 42 000 SEK; Equipment: 12 500 SEK; Total: 54 500 SEK"``."""
    try:
        parsed = parse_budget(lines) if lines else []
    except ValidationError:
        return display_value(lines)
    if not parsed:
        return ""
    parts = [f"{line['label']}: {format_amount(line['amount'])} {currency}" for line in parsed]
    parts.append(f"Total: {format_amount(budget_total(parsed))} {currency}")
    return "; ".join(parts)


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
        elif spec["type"] == "budget":
            out.append((spec["label"], display_budget(value, spec.get("currency", "SEK"))))
        else:
            out.append((spec["label"], display_value(value)))
    return out
