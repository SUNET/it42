"""Built-in form templates, the same on every org site.

``sync_builtins`` creates or updates the rows for ``BUILTIN_TEMPLATES`` by key; a data
migration calls it, and a later built-in (or a change to one) is one more migration
calling it again. Orgs cannot edit or delete built-ins; they load them and save their own.
"""

import copy
from typing import Any

from it42.common.formschema import BASE_FIELDS, DEFAULT_FIELDS


def starting_template() -> list[dict[str, Any]]:
    """What a blank form holds: the base fields and the removable defaults."""
    return copy.deepcopy([*BASE_FIELDS, *DEFAULT_FIELDS])


BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "standard-research-grant",
        "name": "Standard research grant",
        "description": "aims, methods, budget, CV",
        "form_schema": [
            *starting_template(),
            {"name": "project_plan", "label": "Project plan", "type": "heading"},
            {
                "name": "aims",
                "label": "Aims",
                "type": "textarea",
                "required": True,
                "description": "Up to 500 words",
                "max_words": 500,
                "help_text": "What the project will find out or change, and why it matters now.",
            },
            {
                "name": "methods",
                "label": "Methods",
                "type": "textarea",
                "required": True,
                "description": "Up to 1,000 words",
                "max_words": 1000,
                "help_text": (
                    "Reviewers score this section on scientific quality and feasibility. "
                    "Include your approach, timeline and how you will measure success."
                ),
            },
            {
                "name": "budget_breakdown",
                "label": "Budget breakdown",
                "type": "budget",
                "required": True,
                "description": "List the costs you are asking us to cover",
                "currency": "SEK",
                "help_text": "Add one line per cost. Staff costs include social fees.",
            },
            {
                "name": "cv_and_publications",
                "label": (
                    "Attach your CV and a list of your publications as PDFs under Attach documents."
                ),
                "type": "paragraph",
            },
        ],
    },
]


BUILTIN_TEMPLATES.extend(
    [
        {
            "key": "small-grant-quick-apply",
            "name": "Small grant \u2013 quick apply",
            "description": "summary, budget, link",
            "form_schema": [
                *starting_template(),
                {
                    "name": "budget_breakdown",
                    "label": "Budget breakdown",
                    "type": "budget",
                    "required": True,
                    "currency": "SEK",
                    "max_lines": 5,
                    "description": "List the costs you are asking us to cover",
                },
            ],
        },
        {
            "key": "fellowship",
            "name": "Fellowship",
            "description": "research plan and host organisation",
            "form_schema": [
                *starting_template(),
                {"name": "fellowship_details", "label": "Your fellowship", "type": "heading"},
                {
                    "name": "research_plan",
                    "label": "Research plan",
                    "type": "textarea",
                    "required": True,
                    "max_words": 1500,
                    "description": "Up to 1,500 words",
                },
                {
                    "name": "host_organisation",
                    "label": "Host organisation",
                    "type": "text",
                    "required": True,
                },
                {
                    "name": "supervisor",
                    "label": "Host supervisor",
                    "type": "text",
                    "required": True,
                },
            ],
        },
    ]
)


def sync_builtins(form_template_model: Any) -> None:
    """Create or update every built-in template (``form_template_model`` is the
    FormTemplate class, historical in migrations)."""
    for spec in BUILTIN_TEMPLATES:
        form_template_model.objects.update_or_create(
            builtin_key=spec["key"],
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "form_schema": copy.deepcopy(spec["form_schema"]),
            },
        )
