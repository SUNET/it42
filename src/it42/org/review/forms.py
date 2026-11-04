from typing import Any

from django import forms
from django.core.exceptions import ValidationError

from it42.common.forms import BootstrapForm, BootstrapModelForm
from it42.common.pdf import check_pdf_upload

from .models import (
    Assessment,
    Declaration,
    FinalStatement,
    Meeting,
    Panel,
    PanelMember,
    PanelTask,
    ReviewerProfile,
)

DATETIME_LOCAL = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
GRADE = forms.NumberInput(attrs={"min": 0, "max": 10, "step": 1})


class PanelForm(BootstrapModelForm):
    class Meta:
        model = Panel
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class SeatForm(BootstrapForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"placeholder": "name@example.org"}))
    role = forms.ChoiceField(choices=PanelMember.Role.choices, initial=PanelMember.Role.REVIEWER)

    def __init__(self, panel: Panel, *args: Any, **kwargs: Any) -> None:
        self.panel = panel
        super().__init__(*args, **kwargs)

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if PanelMember.objects.filter(panel=self.panel, email=email).exists():
            raise ValidationError("That email already has a seat on this panel.")
        return email


class MeetingForm(BootstrapModelForm):
    class Meta:
        model = Meeting
        fields = ["title", "starts_at", "ends_at", "location", "notes"]
        widgets = {
            "starts_at": DATETIME_LOCAL,
            "ends_at": DATETIME_LOCAL,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        starts, ends = data.get("starts_at"), data.get("ends_at")
        if starts and ends and ends <= starts:
            self.add_error("ends_at", "The end must be after the start.")
        return data


class TaskForm(BootstrapModelForm):
    """A dated task. Past dates are allowed: the FO shortens deadlines on purpose."""

    class Meta:
        model = PanelTask
        fields = ["kind", "title", "starts_at", "ends_at"]
        widgets = {"starts_at": DATETIME_LOCAL, "ends_at": DATETIME_LOCAL}

    def __init__(self, panel: Panel, *args: Any, **kwargs: Any) -> None:
        self.panel = panel
        super().__init__(*args, **kwargs)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        starts, ends = data.get("starts_at"), data.get("ends_at")
        if starts and ends and ends <= starts:
            self.add_error("ends_at", "The end must be after the start.")
        kind = data.get("kind")
        if kind and kind != PanelTask.Kind.OTHER:
            clash = PanelTask.objects.filter(panel=self.panel, kind=kind).exclude(
                pk=self.instance.pk
            )
            if clash.exists():
                self.add_error("kind", "The panel already has a task of this kind.")
        return data


class DeclarationForm(BootstrapModelForm):
    class Meta:
        model = Declaration
        fields = ["in_conflict", "conflict_reason", "competence"]
        labels = {"in_conflict": "I have a conflict of interest with this application"}
        widgets = {"conflict_reason": forms.Textarea(attrs={"rows": 2})}

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("in_conflict") and not (data.get("conflict_reason") or "").strip():
            self.add_error("conflict_reason", "Describe the conflict.")
        return data


class AssessmentForm(BootstrapModelForm):
    class Meta:
        model = Assessment
        fields = ["assessment", "preliminary_statement", "preliminary_grade"]
        labels = {"preliminary_grade": "Preliminary grade (0-10)"}
        widgets = {
            "assessment": forms.Textarea(attrs={"rows": 8}),
            "preliminary_statement": forms.Textarea(attrs={"rows": 4}),
            "preliminary_grade": GRADE,
        }


class FinalStatementForm(BootstrapModelForm):
    class Meta:
        model = FinalStatement
        fields = [field for text, grade, _ in FinalStatement.SECTIONS for field in (text, grade)]
        labels = {
            **{text: label for text, _, label in FinalStatement.SECTIONS},
            **{grade: "Grade (0-10)" for _, grade, _ in FinalStatement.SECTIONS},
        }
        widgets = {
            **{text: forms.Textarea(attrs={"rows": 4}) for text, _, _ in FinalStatement.SECTIONS},
            **{grade: GRADE for _, grade, _ in FinalStatement.SECTIONS},
        }

    def sections(self) -> list[tuple[str, forms.BoundField, forms.BoundField]]:
        """(label, text field, grade field) for the template."""
        return [(label, self[text], self[grade]) for text, grade, label in FinalStatement.SECTIONS]


class PaymentForm(BootstrapModelForm):
    class Meta:
        model = ReviewerProfile
        fields = ["address", "account_holder", "bank_name", "iban", "bic", "keywords"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "keywords": forms.Textarea(attrs={"rows": 2}),
        }


class PassportForm(BootstrapForm):
    passport = forms.FileField(
        label="Passport copy (PDF, 5 MB max)",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
    )
    content: bytes
    sha256: str

    def clean_passport(self) -> Any:
        upload = self.cleaned_data["passport"]
        self.content, self.sha256 = check_pdf_upload(upload)
        return upload
