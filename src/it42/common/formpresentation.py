"""Shared presentation for the builder preview and the real application."""

from typing import Any
from urllib.parse import urlsplit

from django import forms
from django.utils import timezone

from .formschema import BASE_FIELD_NAMES, form_layout, validate_schema


def application_presentation(schema: list[dict[str, Any]], form: forms.BaseForm) -> dict[str, Any]:
    schema = validate_schema(schema)
    rows, identity, number = [], [], 0
    for row in form_layout(schema, form):
        spec = row["spec"]
        if spec["name"] in BASE_FIELD_NAMES:
            identity.append(row)
            continue
        kind = spec["type"]
        if kind in ("deadline", "link"):
            continue
        if kind not in ("heading", "paragraph"):
            number += 1
            kind = "question"
        rows.append({**row, "kind": kind, "number": number})
    budget = next((s for s in schema if s["type"] == "budget" and s.get("max_award")), None)
    links = []
    for spec in schema:
        if spec["type"] == "link" and spec.get("url"):
            url = urlsplit(spec["url"])
            links.append(
                {"url": spec["url"], "text": url.netloc + url.path, "label": spec["label"]}
            )
    return {
        "rows": rows,
        "identity_rows": identity,
        "counts": {
            "questions": number,
            "required": sum(1 for r in rows if r["kind"] == "question" and r["spec"]["required"]),
        },
        "max_award": {"amount": budget["max_award"], "currency": budget["currency"]}
        if budget
        else None,
        "links": links,
        "deadline_zone": timezone.get_current_timezone_name(),
    }
