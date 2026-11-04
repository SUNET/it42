from typing import Any

from django import forms
from django.conf import settings

from it42.common.forms import BootstrapForm, style_fields
from it42.common.formschema import build_form
from it42.core.profiles.models import Document


class DocumentLabelField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj: Any) -> str:
        return f"{obj.original_name} ({obj.size // 1024} KB)"


class ApplicationFormBase(BootstrapForm):
    """Base for the dynamic grant form: adds a picker for the applicant's PDFs."""

    documents = DocumentLabelField(
        queryset=Document.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Attach documents",
        help_text=(
            f"Up to {settings.MAX_ATTACHMENTS} PDFs, "
            f"{settings.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB in total."
        ),
    )

    def __init__(self, *args: Any, user_id: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        documents = self.fields["documents"]
        assert isinstance(documents, forms.ModelMultipleChoiceField)  # noqa: S101
        documents.queryset = Document.objects.filter(user_id=user_id)
        self.order_fields([name for name in self.fields if name != "documents"] + ["documents"])
        style_fields(self)

    def clean_documents(self) -> list[Document]:
        documents = list(self.cleaned_data["documents"])
        if len(documents) > settings.MAX_ATTACHMENTS:
            raise forms.ValidationError(f"Attach at most {settings.MAX_ATTACHMENTS} PDFs.")
        if sum(d.size for d in documents) > settings.MAX_ATTACHMENT_BYTES:
            raise forms.ValidationError("The attached PDFs are too large together.")
        return documents


def application_form(schema: list[dict[str, Any]]) -> type[ApplicationFormBase]:
    return build_form(schema, base=ApplicationFormBase)
