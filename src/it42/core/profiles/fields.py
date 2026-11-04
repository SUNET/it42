"""Partial dates: "YYYY", "YYYY-MM" or "YYYY-MM-DD".

ORCID and the reference CV forms both work in years or year-months, so every start, end
and degree date in the researcher profile is stored as text in this shape. It sorts
chronologically as a string.
"""

import re
from datetime import date
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.db import models

PARTIAL_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
PLACEHOLDER = "YYYY, YYYY-MM or YYYY-MM-DD"


def validate_partial_date(value: str) -> None:
    if not value:
        return
    if not PARTIAL_DATE_RE.match(value):
        raise ValidationError(f"Enter a date as {PLACEHOLDER}.", code="invalid")
    if len(value) == 10:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(f"{value} is not a real date.", code="invalid") from exc


def partial_date_display(value: str) -> str:
    """ "2012-03" -> "March 2012", "2012" -> "2012", "2012-03-05" -> "5 March 2012"."""
    parts = value.split("-") if value else []
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]  # fmt: skip
    if len(parts) == 2:
        return f"{months[int(parts[1]) - 1]} {parts[0]}"
    if len(parts) == 3:
        return f"{int(parts[2])} {months[int(parts[1]) - 1]} {parts[0]}"
    return value


class PartialDateFormField(forms.CharField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 10)
        kwargs.setdefault("widget", forms.TextInput(attrs={"placeholder": PLACEHOLDER}))
        super().__init__(**kwargs)
        self.validators.append(validate_partial_date)

    def to_python(self, value: Any) -> str:
        return str(super().to_python(value) or "").strip()


class PartialDateField(models.CharField):
    """A CharField holding a partial date; validated on forms and on ``full_clean``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 10)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)
        if validate_partial_date not in self.validators:
            self.validators.append(validate_partial_date)

    def formfield(self, **kwargs: Any) -> Any:
        kwargs.setdefault("form_class", PartialDateFormField)
        return super().formfield(**kwargs)
