"""Activity feeds on the card detail pages (the Activity tab of every role): events
newest first, grouped by month. Each zone builds its own events from its own rows."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby

from django.utils import timezone


@dataclass(frozen=True)
class Event:
    when: datetime
    who: str
    text: str
    detail: str = ""
    note: bool = False


@dataclass(frozen=True)
class Month:
    title: str
    events: list[Event] = field(default_factory=list)


def by_month(events: Iterable[Event]) -> list[Month]:
    ordered = sorted(events, key=lambda e: e.when, reverse=True)
    return [
        Month(title, list(group))
        for title, group in groupby(
            ordered, key=lambda e: timezone.localtime(e.when).strftime("%B %Y")
        )
    ]
