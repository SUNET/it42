"""One ModelForm per CV section.

The conditional rules of the reference portal are reduced to: a text box is required when
the matching choice is "other", end dates come after start dates, and a handful of
"required by kind" rules. Everything else is optional in the PoC.
"""

from typing import Any

from django import forms

from it42.common.forms import BootstrapModelForm

from .models import (
    AssociateProfessorship,
    Award,
    AwardedGrant,
    BasicEducation,
    Employment,
    IntellectualProperty,
    OtherMerit,
    Position,
    PostdocPeriod,
    Publication,
    ResearchEducation,
    ResearchExchange,
    ResearchInterruption,
    Supervision,
)

TEXTAREA = forms.Textarea(attrs={"rows": 3})


class LinesField(forms.Field):
    """A list of strings edited as one entry per line (used for authors and editors)."""

    widget = forms.Textarea(attrs={"rows": 4})

    def prepare_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return "\n".join(str(v) for v in value)
        return value

    def to_python(self, value: Any) -> list[str]:
        if value in self.empty_values:
            return []
        return [line.strip() for line in str(value).splitlines() if line.strip()]


class EntryForm(BootstrapModelForm):
    """Shared helpers; ``self.instance.profile`` is set by the view before validation."""

    def require_other(self, choice: str, text: str, other: str = "other") -> None:
        data = self.cleaned_data
        if data.get(choice) == other and not data.get(text):
            self.add_error(text, "Please describe it.")

    def check_range(self, start: str = "start_date", end: str = "end_date") -> None:
        data = self.cleaned_data
        first, last = str(data.get(start) or ""), str(data.get(end) or "")
        if first and last and last.ljust(10, "9") < first.ljust(10, "0"):
            self.add_error(end, "The end must not be before the start.")

    def clean(self) -> dict[str, Any]:
        return super().clean() or {}


class BasicEducationForm(EntryForm):
    class Meta:
        model = BasicEducation
        fields = [
            "university",
            "department",
            "year",
            "subject",
            "degree",
            "other_degree",
            "specialist_training",
            "specialist_training_year",
            "specialist_training_description",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.require_other("degree", "other_degree")
        return data


class ResearchEducationForm(EntryForm):
    class Meta:
        model = ResearchEducation
        fields = [
            "university",
            "department",
            "kind",
            "subject",
            "degree_date",
            "thesis_title",
            "thesis_title_en",
            "isbn",
            "supervisor_first_name",
            "supervisor_last_name",
            "competence_date",
            "competence_description_sv",
            "competence_description_en",
        ]
        widgets = {"competence_description_sv": TEXTAREA, "competence_description_en": TEXTAREA}

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("kind") == ResearchEducation.Kind.COMPETENCE:
            if not data.get("competence_date"):
                self.add_error("competence_date", "Required for equivalent competence.")
            if not (data.get("competence_description_sv") or data.get("competence_description_en")):
                self.add_error("competence_description_en", "Describe the competence.")
        elif not data.get("degree_date"):
            self.add_error("degree_date", "Enter the date of the degree.")
        return data


class EmploymentForm(EntryForm):
    research_share = forms.IntegerField(
        label="Share of research (%)", min_value=0, max_value=100, required=False
    )

    class Meta:
        model = Employment
        fields = [
            "employer",
            "department",
            "position",
            "other_position",
            "form_of_employment",
            "start_date",
            "end_date",
            "is_present",
            "research_share",
            "other_information",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.require_other("position", "other_position", Position.OTHER)
        if data.get("is_present"):
            data["end_date"] = ""
        elif not data.get("end_date"):
            self.add_error("end_date", "Enter an end date or mark the position as current.")
        self.check_range()
        return data


class PostdocPeriodForm(EntryForm):
    class Meta:
        model = PostdocPeriod
        fields = ["host", "department", "subject", "start_date", "end_date", "months"]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.check_range()
        return data


class ResearchExchangeForm(EntryForm):
    class Meta:
        model = ResearchExchange
        fields = [
            "kind",
            "custom_kind",
            "host",
            "department",
            "subject",
            "start_date",
            "end_date",
            "months",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.require_other("kind", "custom_kind")
        self.check_range()
        return data


class ResearchInterruptionForm(EntryForm):
    class Meta:
        model = ResearchInterruption
        fields = ["start_date", "end_date", "description"]
        widgets = {"description": TEXTAREA}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["start_date"].required = True

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.check_range()
        return data


class AssociateProfessorshipForm(EntryForm):
    class Meta:
        model = AssociateProfessorship
        fields = ["university", "department", "subject", "year"]


class SupervisionForm(EntryForm):
    class Meta:
        model = Supervision
        fields = [
            "kind",
            "role",
            "supervised_type",
            "first_name",
            "last_name",
            "number_of_people",
            "person_university",
            "person_department",
            "supervisor_university",
            "supervisor_department",
            "end_year",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("kind") == Supervision.Kind.GROUP:
            if not data.get("number_of_people"):
                self.add_error("number_of_people", "How many people did you supervise?")
        elif not (data.get("first_name") or data.get("last_name")):
            self.add_error("last_name", "Enter the name of the person you supervised.")
        return data


class AwardedGrantForm(EntryForm):
    class Meta:
        model = AwardedGrant
        fields = [
            "funder",
            "country",
            "project_title",
            "reference_number",
            "role",
            "applicant",
            "start_year",
            "end_year",
            "amount",
            "own_share",
            "currency",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        start, end = data.get("start_year"), data.get("end_year")
        if start and end and end < start:
            self.add_error("end_year", "The end must not be before the start.")
        return data


class AwardForm(EntryForm):
    class Meta:
        model = Award
        fields = ["award", "issuer", "country", "year", "description"]
        widgets = {"description": TEXTAREA}


class OtherMeritForm(EntryForm):
    class Meta:
        model = OtherMerit
        fields = ["title", "start_year", "end_year", "description"]
        widgets = {"description": TEXTAREA}

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        start, end = data.get("start_year"), data.get("end_year")
        if start and end and end < start:
            self.add_error("end_year", "The end must not be before the start.")
        return data


class IntellectualPropertyForm(EntryForm):
    class Meta:
        model = IntellectualProperty
        fields = [
            "kind",
            "other_kind",
            "title",
            "number",
            "date_approved",
            "classification",
            "licensed",
            "licensee_type",
        ]

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        self.require_other("kind", "other_kind")
        if not (data.get("title") or data.get("number")):
            self.add_error("title", "Enter a title or a registration number.")
        return data


class PublicationForm(EntryForm):
    authors = LinesField(required=False, help_text="One author per line, in order.")
    editors = LinesField(required=False, help_text="One editor per line, in order.")

    class Meta:
        model = Publication
        fields = [
            "category",
            "form",
            "status",
            "title",
            "authors",
            "editors",
            "journal",
            "publisher",
            "place",
            "publication_date",
            "volume",
            "issue",
            "first_page",
            "last_page",
            "doi",
            "isbn",
            "open_access",
            "link",
            "abstract",
        ]
        widgets = {
            "title": forms.Textarea(attrs={"rows": 2}),
            "journal": forms.Textarea(attrs={"rows": 1}),
            "abstract": TEXTAREA,
        }

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        form = data.get("form")
        if form != Publication.Form.EDITORSHIP and not data.get("authors"):
            self.add_error("authors", "Enter at least one author.")
        if form in (Publication.Form.BOOK_CHAPTER, Publication.Form.EDITORSHIP) and not data.get(
            "editors"
        ):
            self.add_error("editors", "Enter at least one editor.")
        return data
