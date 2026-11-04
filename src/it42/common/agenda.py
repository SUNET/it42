"""The right panel of the role dashboards (Dashboard / Granter, Dashboard / Reviewer,
Dashboard / Organization):
a month calendar whose days carry coloured dots for dated items, and the list of
upcoming deadlines. Only real dates go in: grant deadlines, signature deadlines,
review tasks, meetings."""

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any

# Dot colour per kind (static/it42/org.css .it-dot-<kind>), with the legend text.
KINDS = {
    "call": "Call closes",
    "signoff": "Organisation sign-off",
    "task": "Review task",
    "meeting": "Meeting",
}


@dataclass(frozen=True)
class Deadline:
    title: str
    detail: str
    when: date
    kind: str  # a KINDS key


def agenda(today: date, deadlines: list[Deadline], upcoming: int = 5) -> dict[str, Any]:
    """Template context for includes/agenda.html: this month's weeks and the next
    ``upcoming`` deadlines from today on."""
    marks: dict[date, list[str]] = {}
    for item in deadlines:
        kinds = marks.setdefault(item.when, [])
        if item.kind not in kinds:
            kinds.append(item.kind)
    weeks = [
        [
            {
                "day": day,
                "in_month": day.month == today.month,
                "is_today": day == today,
                "kinds": marks.get(day, []),
            }
            for day in week
        ]
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month)
    ]
    used = {kind for kinds in marks.values() for kind in kinds}
    return {
        "month": today,
        "weekdays": ["M", "T", "W", "T", "F", "S", "S"],
        "weeks": weeks,
        "legend": [(kind, label) for kind, label in KINDS.items() if kind in used],
        "deadlines": sorted(
            (d for d in deadlines if d.when >= today), key=lambda d: (d.when, d.title)
        )[:upcoming],
    }
