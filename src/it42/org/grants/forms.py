import copy
import json
from typing import Any

from django import forms
from django.utils import timezone

from it42.common.forms import BootstrapForm, BootstrapModelForm
from it42.common.formschema import (
    BASE_FIELDS,
    SchemaError,
    assign_names,
    require_base_fields,
    validate_schema,
)

from .models import SIGNATURE_DAYS, Grant, default_signature_deadline


def starting_template() -> list[dict[str, Any]]:
    """What a new grant's form starts from: the base fields (the applicant's name and
    email, and the administrating organisation)."""
    return copy.deepcopy(BASE_FIELDS)


class PrettyJSONField(forms.JSONField):
    def prepare_value(self, value: Any) -> Any:
        if isinstance(value, list | dict):
            return json.dumps(value, indent=2, ensure_ascii=False)
        return super().prepare_value(value)


class GrantForm(BootstrapModelForm):
    form_schema = PrettyJSONField(
        required=False,
        label="Application form",
        widget=forms.Textarea(attrs={"rows": 12, "class": "font-monospace"}),
        help_text=(
            "A list of fields with label, type and required; names are derived from the "
            "labels when you save. Applicants attach PDFs separately."
        ),
    )

    signature_deadline = forms.DateField(
        required=False,
        label="Signature deadline",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text=(
            "Last day administrating organisations can sign applications. Empty: "
            f"{SIGNATURE_DAYS} days after the call closes. You can move it later."
        ),
    )

    class Meta:
        model = Grant
        fields = ["title", "description", "deadline", "signature_deadline", "form_schema"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.is_bound:
            self.initial.setdefault("form_schema", starting_template())

    def clean_form_schema(self) -> list[dict[str, Any]]:
        try:
            # Names come from labels, never from the user (or the JSON editor).
            schema = validate_schema(assign_names(self.cleaned_data.get("form_schema") or []))
            require_base_fields(schema)
        except SchemaError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return schema

    def clean_deadline(self) -> Any:
        deadline = self.cleaned_data["deadline"]
        if deadline < timezone.localdate():
            raise forms.ValidationError("The deadline is in the past.")
        return deadline

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        deadline = cleaned.get("deadline")
        if deadline is not None:
            signature_deadline = cleaned.get("signature_deadline")
            if signature_deadline is None:
                cleaned["signature_deadline"] = default_signature_deadline(deadline)
            elif signature_deadline < deadline:
                self.add_error(
                    "signature_deadline", "The signature deadline cannot be before the deadline."
                )
        return cleaned


class SignatureDeadlineForm(BootstrapForm):
    """Move a grant's signature deadline (any time, also after the call closed)."""

    signature_deadline = forms.DateField(
        label="Signature deadline", widget=forms.DateInput(attrs={"type": "date"})
    )
