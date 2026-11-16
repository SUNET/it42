import json
from typing import Any

from django import forms
from django.utils import timezone

from it42.common.forms import BootstrapForm, BootstrapModelForm
from it42.common.formschema import (
    SchemaError,
    assign_names,
    require_base_fields,
    validate_schema,
)

from .models import (
    DEFAULT_DEADLINE_TIME,
    SIGNATURE_DAYS,
    Category,
    Folder,
    FormTemplate,
    Grant,
    default_signature_deadline,
)
from .templates import starting_template


class PrettyJSONField(forms.JSONField):
    def prepare_value(self, value: Any) -> Any:
        if isinstance(value, list | dict):
            return json.dumps(value, indent=2, ensure_ascii=False)
        return super().prepare_value(value)


def clean_schema(raw: object) -> list[dict[str, Any]]:
    """The schema as the org saves it: names from labels, validated, base fields kept."""
    schema = validate_schema(assign_names(raw or []))
    require_base_fields(schema)
    return schema


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
    deadline_time = forms.TimeField(
        required=False,
        label="Closing time",
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        help_text=f"Applications close at this time ({timezone.get_current_timezone_name()}).",
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
    folder = forms.ModelChoiceField(
        Folder.objects.all(), required=False, empty_label="No folder", label="Folder"
    )
    category = forms.ModelChoiceField(
        Category.objects.all(), required=False, empty_label="No category", label="Category"
    )
    # Set by the builder when a saved template is loaded; never shown.
    template = forms.ModelChoiceField(
        FormTemplate.objects.all(), required=False, widget=forms.HiddenInput
    )

    class Meta:
        model = Grant
        fields = [
            "title",
            "description",
            "deadline",
            "deadline_time",
            "signature_deadline",
            "folder",
            "category",
            "template",
            "form_schema",
        ]
        labels = {"title": "Grant title", "deadline": "Application deadline"}
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
            return clean_schema(self.cleaned_data.get("form_schema"))
        except SchemaError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_deadline(self) -> Any:
        deadline = self.cleaned_data["deadline"]
        if deadline < timezone.localdate():
            raise forms.ValidationError("The deadline is in the past.")
        return deadline

    def clean_deadline_time(self) -> Any:
        """An empty time means the default closing time (a plain POST without the field,
        as the acceptance script sends, must keep working)."""
        return self.cleaned_data.get("deadline_time") or DEFAULT_DEADLINE_TIME

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


class NameForm(BootstrapForm):
    """One name: a new or renamed folder, category or template."""

    name = forms.CharField(max_length=100, label="Name")

    def __init__(self, *args: Any, taken: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.taken = taken

    def clean_name(self) -> str:
        """Collapse whitespace and refuse a name that ``taken`` already holds (case
        ignored, so "Water" and "water" are the same folder)."""
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter a name.")
        if self.taken is not None and self.taken.filter(name__iexact=name).exists():
            raise forms.ValidationError(f"There is already one called {name!r}.")
        return name
