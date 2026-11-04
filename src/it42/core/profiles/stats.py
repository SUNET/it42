"""Figures for the profile page, computed from the CV only.

The design's citations, h-index and AI summaries have no data here (ORCID's public API has
no citation counts), so they are not shown.

The CV is loaded once per page (``load_cv``: one query per section) and every figure, the
Academic CV table and Edit data are computed from that.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.urls import reverse

from .models import (
    AssociateProfessorship,
    CVEntry,
    Employment,
    IntellectualProperty,
    Profile,
    Publication,
    ResearchEducation,
    ResearchExchange,
    ResearchInterruption,
    Supervision,
)
from .sections import SECTIONS, Section

CV = dict[str, list[Any]]  # section key -> that section's entries, in sort order


@dataclass(frozen=True)
class Fact:
    value: str
    label: str


@dataclass(frozen=True)
class Row:
    """One row of the Academic CV table."""

    section: Section
    entry: CVEntry
    summary: str
    details: str
    dates: str
    sort_date: str

    @property
    def search_text(self) -> str:
        return f"{self.summary} {self.details} {self.section.short}".casefold()


def load_cv(profile: Profile) -> CV:
    return {key: list(s.model.objects.filter(profile=profile)) for key, s in SECTIONS.items()}


def month_index(value: str, *, end: bool = False) -> int | None:
    """A partial date as a month count; a missing month is January, or December for an end."""
    if not value:
        return None
    month = int(value[5:7]) if len(value) >= 7 else (12 if end else 1)
    return int(value[:4]) * 12 + month


def months_of(start: str, end: str) -> int:
    """Whole months from one partial date to another (missing months count as January)."""
    first, last = month_index(start), month_index(end)
    if first is None or last is None:
        return 0
    return max(last - first, 0)


def duration(months: int) -> str:
    """ "9 y 2 m", "1 y", "9 months"."""
    years, rest = divmod(months, 12)
    if not years:
        return f"{rest} month{'s' if rest != 1 else ''}"
    return f"{years} y {rest} m" if rest else f"{years} y"


def plural(count: int, word: str) -> str:
    return f"{word}{'s' if count != 1 else ''}"


def cv_rows(cv: CV) -> list[Row]:
    """Every CV entry, newest first."""
    rows = [
        Row(
            SECTIONS[key], entry, entry.summary(), entry.details(), entry.dates(), entry.sort_date()
        )
        for key, entries in cv.items()
        for entry in entries
    ]
    rows.sort(key=lambda r: r.sort_date, reverse=True)
    return rows


def sort_rows(rows: list[Row], order: str) -> list[Row]:
    keys = list(SECTIONS)
    if order == "oldest":
        return sorted(rows, key=lambda r: r.sort_date or "9999")
    if order == "section":
        return sorted(rows, key=lambda r: (r.section.short, keys.index(r.section.key)))
    return sorted(rows, key=lambda r: r.sort_date, reverse=True)


def current_employment(cv: CV) -> Employment | None:
    return next((e for e in cv["employment"] if e.is_present), None)


def publication_counts(cv: CV) -> tuple[int, int, int]:
    """(all, peer reviewed, conference contributions)."""
    publications: list[Publication] = cv["publication"]
    peer = sum(p.category == Publication.Category.PEER_REVIEWED for p in publications)
    conference = sum(p.form == Publication.Form.CONFERENCE for p in publications)
    return len(publications), peer, conference


def record_tiles(cv: CV) -> list[Fact]:
    """The Academic record / Stats tiles."""
    total, peer, conference = publication_counts(cv)
    grants = len(cv["grant"])
    return [
        Fact(str(total), "Publications"),
        Fact(str(peer), "Peer reviewed"),
        Fact(str(grants), plural(grants, "Awarded grant")),
        Fact(str(conference), plural(conference, "Conference contribution")),
    ]


def leave_since(start: int, today: int, interruptions: list[ResearchInterruption]) -> int:
    """Months of research interruptions that overlap ``start`` .. ``today`` (month counts)."""
    months = 0
    for i in interruptions:
        first = month_index(i.start_date)
        last = month_index(i.end_date, end=True) if i.end_date else today
        if first is not None and last is not None:
            months += max(min(last, today) - max(first, start), 0)
    return months


def key_facts(cv: CV, today: date | None = None) -> list[Fact]:
    """Overview tiles; a fact without data is left out."""
    today = today or date.today()
    facts: list[Fact] = []

    docents: list[AssociateProfessorship] = [d for d in cv["docent"] if d.year]
    if docents:
        docent = min(docents, key=lambda d: d.year or 0)
        facts.append(Fact(str(docent.year), f"Docent in {docent.subject or docent.university}"))

    phds: list[ResearchEducation] = [
        r
        for r in cv["research_education"]
        if r.kind == ResearchEducation.Kind.PHD and r.degree_date
    ]
    if phds:
        degree = month_index(min(r.degree_date for r in phds)) or 0
        now = today.year * 12 + today.month
        leave = leave_since(degree, now, cv["interruption"])
        since = max(now - degree - leave, 0)
        facts.append(Fact(duration(since), "Since PhD, after leave" if leave else "Since PhD"))

    total, peer, _ = publication_counts(cv)
    if total:
        facts.append(Fact(str(total), f"Publications · {peer} peer reviewed"))

    grants = len(cv["grant"])
    if grants:
        facts.append(Fact(str(grants), plural(grants, "Awarded grant")))

    doctoral = master = 0
    supervisions: list[Supervision] = cv["supervision"]
    for s in supervisions:
        people = (s.number_of_people or 0) if s.kind == Supervision.Kind.GROUP else 1
        if s.supervised_type in (
            Supervision.SupervisedType.PHD,
            Supervision.SupervisedType.LICENTIATE,
        ):
            doctoral += people
        elif s.supervised_type == Supervision.SupervisedType.MASTER:
            master += people
    if doctoral and master:
        facts.append(Fact(f"{doctoral} + {master}", "PhD and Master's students"))
    elif doctoral or master:
        count = doctoral or master
        facts.append(Fact(str(count), "PhD students" if doctoral else "Master's students"))

    exchanges: list[ResearchExchange] = cv["exchange"]
    exchange_months = sum(e.months or months_of(e.start_date, e.end_date) for e in exchanges)
    if exchange_months:
        facts.append(Fact(duration(exchange_months), "Research exchanges"))

    awards = len(cv["award"])
    if awards:
        facts.append(Fact(str(awards), "Awards and distinctions"))

    patents: list[IntellectualProperty] = [
        p for p in cv["ip"] if p.kind == IntellectualProperty.Kind.PATENT
    ]
    if patents:
        granted = sum(bool(p.date_approved) for p in patents)
        pending = len(patents) - granted
        if granted and pending:
            facts.append(Fact(f"{granted} + {pending}", "Patents granted and pending"))
        else:
            facts.append(
                Fact(str(granted or pending), "Patents granted" if granted else "Patents pending")
            )
    return facts


@dataclass(frozen=True)
class Step:
    label: str
    done: bool
    anchor: str  # where "Finish profile" goes while the step is open


def profile_steps(profile: Profile, has_entries: bool, has_documents: bool) -> list[Step]:
    """ "Finish your profile": the steps that make an application easy to assess."""
    return [
        Step("add your name", bool(profile.full_name), reverse("profile_edit")),
        Step("add your ORCID iD", bool(profile.orcid), reverse("orcid_start")),
        Step("write a short biography", bool(profile.bio), reverse("profile_edit")),
        Step("add your CV", has_entries, reverse("profile_data")),
        Step("upload a PDF, such as your CV", has_documents, f"{reverse('profile')}#cv-upload"),
    ]
