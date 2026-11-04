from typing import Any

from django import forms


def style_fields(form: forms.BaseForm) -> None:
    """Add Bootstrap classes to every widget, and mark invalid fields.

    Reads errors only if the form was already validated: touching ``form.errors``
    here would validate it before subclasses finish setting up their fields.
    """
    errors = getattr(form, "_errors", None) or {}
    for name, field in form.fields.items():
        widget = field.widget
        if isinstance(
            widget, forms.CheckboxInput | forms.CheckboxSelectMultiple | forms.RadioSelect
        ):
            css = "form-check-input"
        elif isinstance(widget, forms.Select):
            css = "form-select"
        else:
            css = "form-control"
        classes = [c for c in widget.attrs.get("class", "").split() if c != "is-invalid"]
        if css not in classes:
            classes.append(css)
        if name in errors:
            classes.append("is-invalid")
        widget.attrs["class"] = " ".join(classes)


class BootstrapForm(forms.Form):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        style_fields(self)

    def full_clean(self) -> None:
        super().full_clean()
        style_fields(self)


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        style_fields(self)

    def full_clean(self) -> None:
        super().full_clean()
        style_fields(self)
