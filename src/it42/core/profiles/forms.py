from typing import Any

from django import forms

from it42.common.forms import BootstrapForm, BootstrapModelForm
from it42.common.pdf import check_pdf_upload

from .models import AcademicTitle, Profile
from .orcid import OrcidError, normalise_orcid


def clean_orcid_text(text: str) -> str:
    if not text.strip():
        return ""
    try:
        return normalise_orcid(text)
    except OrcidError as exc:
        raise forms.ValidationError(str(exc)) from exc


class ProfileForm(BootstrapModelForm):
    """Edit profile: what the profile column shows."""

    # Declared here without the model validator so that ``clean_orcid`` can accept the
    # https://orcid.org/... form and store the bare iD.
    orcid = forms.CharField(
        label="ORCID iD",
        required=False,
        max_length=64,
        help_text="For example 0000-0002-1825-0097, or the https://orcid.org/… link.",
    )

    class Meta:
        model = Profile
        fields = [
            "first_name",
            "last_name",
            "academic_title",
            "other_academic_title",
            "orcid",
            "bio",
        ]
        widgets = {"bio": forms.Textarea(attrs={"rows": 5})}

    def clean_orcid(self) -> str:
        return clean_orcid_text(self.cleaned_data.get("orcid", "") or "")

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        title = data.get("academic_title")
        if title == AcademicTitle.OTHER and not data.get("other_academic_title"):
            self.add_error("other_academic_title", "Describe the academic title.")
        return data


class PersonalInfoForm(BootstrapModelForm):
    """The private Personal info tab, shown in two groups."""

    GROUPS = (
        ("Contact", ("address", "phone", "telephone", "secondary_email", "homepage")),
        ("Identity", ("date_of_birth", "gender", "nationality", "country_of_activity")),
    )

    def groups(self) -> list[tuple[str, list[forms.BoundField]]]:
        return [(title, [self[name] for name in names]) for title, names in self.GROUPS]

    class Meta:
        model = Profile
        fields = [
            "address",
            "phone",
            "telephone",
            "secondary_email",
            "homepage",
            "date_of_birth",
            "gender",
            "nationality",
            "country_of_activity",
        ]
        labels = {"address": "Home address", "secondary_email": "Personal email"}
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 3}),
        }


class ResearchAreasForm(BootstrapForm):
    areas = forms.CharField(
        label="Research areas",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One per line, or separated by commas. Shown as tags on your profile.",
    )

    def clean_areas(self) -> list[str]:
        text = self.cleaned_data.get("areas") or ""
        seen: set[str] = set()
        areas: list[str] = []
        for part in text.replace(",", "\n").splitlines():
            area = part.strip()[:100]
            if area and area.casefold() not in seen:
                seen.add(area.casefold())
                areas.append(area)
        if len(areas) > 30:
            raise forms.ValidationError("Keep it to 30 research areas.")
        return areas


class OrcidStartForm(BootstrapForm):
    orcid = forms.CharField(
        label="ORCID iD",
        max_length=64,
        help_text="For example 0000-0002-1825-0097, or the https://orcid.org/… link.",
    )

    def clean_orcid(self) -> str:
        return clean_orcid_text(self.cleaned_data.get("orcid", "") or "")


class DocumentUploadForm(BootstrapForm):
    file = forms.FileField(
        label="PDF document",
        help_text="PDF only, up to 5 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf"}),
    )

    def clean_file(self) -> object:
        upload = self.cleaned_data["file"]
        self.content, self.sha256 = check_pdf_upload(upload)
        return upload
