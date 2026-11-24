"""The VR national infrastructure question shared by grant previews and applications."""

from pathlib import Path
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.http import QueryDict

# Keep the supplied names as the wire values so submitted answers remain self-contained.
NAMES = sorted(
    Path(__file__).with_name("national_infrastructures.txt").read_text("utf-8").splitlines(),
    key=str.casefold,
)
OTHER = "Other, specify below"
MAX_OTHER = 2000


class InfrastructureWidget(forms.Widget):
    """Read one compound answer from an applicant POST or a submitted event."""

    template_name = "it42/widgets/national_infrastructure.html"

    def value_from_datadict(self, data: Any, files: Any, name: str) -> Any:
        """Use dotted input names so another schema field cannot shadow a subfield."""
        if not isinstance(data, QueryDict):
            return data.get(name)
        use = data.get(f"{name}.use")
        if use != "yes":
            # Discard hidden details when an applicant switches their answer to No.
            return {"use": use} if use else None
        return {
            "use": use,
            "selected": data.getlist(f"{name}.selected"),
            "other": data.get(f"{name}.other", ""),
        }

    def get_context(self, name: str, value: Any, attrs: Any) -> dict[str, Any]:
        """Expose the raw draft or bound answer so incomplete entries can be resumed."""
        context = super().get_context(name, value, attrs)
        context.update(answer=value or {}, names=NAMES, other_label=OTHER, max_other=MAX_OTHER)
        return context

    def id_for_label(self, id_: str) -> str:
        """Associate the surrounding question label with the first radio button."""
        return f"{id_}_yes"


class InfrastructureField(forms.Field):
    """Validate Yes/No and, for Yes, at least one listed or applicant-supplied name."""

    widget = InfrastructureWidget

    def to_python(self, value: Any) -> dict[str, Any] | None:
        """Validate both browser answers and the JSON payload rechecked by the funder."""
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("use") not in ("yes", "no"):
            raise ValidationError("Choose Yes or No.")
        if value == {"use": "no"}:
            return value
        if value["use"] != "yes" or set(value) != {"use", "selected", "other"}:
            raise ValidationError("The infrastructure answer has unexpected details.")
        selected, other = value["selected"], value["other"]
        if not isinstance(selected, list) or any(
            name != OTHER and name not in NAMES for name in selected
        ):
            raise ValidationError("Choose infrastructures from the list provided.")
        if not isinstance(other, str) or len(other) > MAX_OTHER:
            raise ValidationError(f"Use at most {MAX_OTHER} characters for other infrastructures.")
        other = other.strip()
        if OTHER in selected and not other:
            raise ValidationError("Enter the name of the other infrastructure.")
        if not selected and not other:
            raise ValidationError("Select an infrastructure or enter an unlisted name.")
        return {"use": "yes", "selected": list(dict.fromkeys(selected)), "other": other}


def display_infrastructure(answer: Any) -> str:
    """Show submitted names and free text in applicant, funder, reviewer and signing views."""
    if not answer:
        return ""
    if answer["use"] == "no":
        return "No"
    lines = ["Yes", *(name for name in answer["selected"] if name != OTHER)]
    if answer["other"]:
        lines.append(answer["other"])
    return "\n".join(lines)
