"""Map an ORCID record (Public API v3.0 JSON) onto profile fields and CV entries.

Pure functions, no database access. ``map_record`` returns plain dicts keyed by section
(see ``sections.SECTIONS``); each entry dict carries ``orcid_put_code`` plus model fields.
Which ORCID activities feed which section is listed in ``sections.SECTIONS`` (``orcid_source``).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .fields import PARTIAL_DATE_RE
from .models import (
    AwardedGrant,
    BasicEducation,
    IntellectualProperty,
    Position,
    Publication,
    ResearchEducation,
    ResearchExchange,
)

ORG_NAME = "organization"


@dataclass
class Imported:
    orcid: str
    profile: dict[str, Any] = field(default_factory=dict)  # filled only when empty
    person: dict[str, Any] = field(default_factory=dict)  # Profile.orcid_person, replaced
    entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def add(self, section: str, entry: dict[str, Any]) -> None:
        self.entries.setdefault(section, []).append(entry)


def dig(data: Any, *keys: str) -> Any:
    """``dig(d, "a", "b")`` → ``d["a"]["b"]`` or None when any step is missing."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def text(data: Any, *keys: str) -> str:
    value = dig(data, *keys)
    return str(value).strip() if value not in (None, "") else ""


def partial_date(data: Any) -> str:
    """``{"year": {"value": "2012"}, "month": {"value": "03"}, "day": null}`` → ``2012-03``.

    An impossible day (ORCID's demo record starts a job on 29 February 1930) is dropped so
    the entry still passes the edit form's validation.
    """
    parts = []
    for key in ("year", "month", "day"):
        value = text(data, key, "value")
        if not value.isdigit():
            break
        parts.append(value.zfill(4 if key == "year" else 2))
    while parts and not PARTIAL_DATE_RE.match("-".join(parts)):
        parts.pop()
    if len(parts) == 3:
        try:
            date.fromisoformat("-".join(parts))
        except ValueError:
            parts.pop()
    return "-".join(parts)


def year_of(data: Any) -> int | None:
    value = text(data, "year", "value")
    return int(value) if value.isdigit() else None


def months_between(start: str, end: str) -> int | None:
    if len(start) < 7 or len(end) < 7:
        return None
    months = (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7])
    return months if months >= 0 else None


def org_fields(item: Any) -> tuple[str, str, str]:
    """(organisation name, department, country) of an affiliation-like item."""
    return (
        text(item, ORG_NAME, "name"),
        text(item, "department-name"),
        text(item, ORG_NAME, "address", "country"),
    )


def external_ids(item: Any) -> list[dict[str, str]]:
    ids = dig(item, "external-ids", "external-id") or []
    return [
        {
            "type": text(i, "external-id-type").lower(),
            "value": text(i, "external-id-value"),
            "url": text(i, "external-id-url", "value"),
            "relationship": text(i, "external-id-relationship").lower(),
        }
        for i in ids
        if isinstance(i, dict)
    ]


def self_id(item: Any, kind: str) -> str:
    for ext in external_ids(item):
        if ext["type"] == kind and ext["relationship"] in ("self", ""):
            return ext["value"]
    return ""


def has(title: str, *needles: str) -> bool:
    lowered = title.lower()
    return any(needle in lowered for needle in needles)


def position_from(title: str) -> str:
    if has(title, "associate professor", "docent"):
        return Position.ASSOCIATE_PROFESSOR
    if has(title, "senior lecturer"):
        return Position.SENIOR_LECTURER
    if has(title, "lecturer"):
        return Position.LECTURER
    if has(title, "postdoc", "post-doc"):
        return Position.POSTDOC
    if has(title, "phd student", "ph.d. student", "doctoral student", "graduate student"):
        return Position.PHD_STUDENT
    if has(title, "professor"):
        return Position.PROFESSOR
    if has(title, "researcher", "scientist", "research fellow"):
        return Position.RESEARCHER
    return Position.OTHER


def is_research_degree(title: str) -> bool:
    return has(title, "phd", "ph.d", "doctor", "dr.", "licentiate", "dphil", "d.phil")


def is_docent(title: str) -> bool:
    return has(title, "docent", "associate professor", "habilitation", "reader")


def degree_from(title: str) -> str:
    if has(title, "bachelor", "b.sc", "bsc", "b.a.", "ba ", "b.eng", "beng"):
        return BasicEducation.Degree.BACHELOR
    if has(title, "master", "m.sc", "msc", "m.a.", "ma ", "m.eng", "meng", "civilingenj"):
        return BasicEducation.Degree.MASTER
    if has(title, "m.d.", "md ", "medical degree", "läkarexamen"):
        return BasicEducation.Degree.PROFESSIONAL
    return BasicEducation.Degree.OTHER


WORK_FORMS: dict[str, str] = {
    "journal-article": Publication.Form.JOURNAL_ARTICLE,
    "book": Publication.Form.BOOK,
    "book-chapter": Publication.Form.BOOK_CHAPTER,
    "edited-book": Publication.Form.EDITORSHIP,
    "conference-paper": Publication.Form.CONFERENCE,
    "conference-abstract": Publication.Form.CONFERENCE,
    "conference-poster": Publication.Form.CONFERENCE,
    "conference-presentation": Publication.Form.CONFERENCE,
    "conference-output": Publication.Form.CONFERENCE,
    "review": Publication.Form.REVIEW_ARTICLE,
    "book-review": Publication.Form.REVIEW_ARTICLE,
    "preprint": Publication.Form.PREPRINT,
    "dissertation-thesis": Publication.Form.THESIS,
    "dissertation": Publication.Form.THESIS,
    "report": Publication.Form.REPORT,
    "working-paper": Publication.Form.REPORT,
    "data-set": Publication.Form.DATASET,
    "software": Publication.Form.SOFTWARE,
    "magazine-article": Publication.Form.OTHER_LITERATURE,
    "newspaper-article": Publication.Form.OTHER_LITERATURE,
    "online-resource": Publication.Form.OTHER_LITERATURE,
    "website": Publication.Form.OTHER_LITERATURE,
    "encyclopedia-entry": Publication.Form.OTHER_LITERATURE,
    "dictionary-entry": Publication.Form.OTHER_LITERATURE,
}
PEER_REVIEWED_FORMS = {
    Publication.Form.JOURNAL_ARTICLE,
    Publication.Form.CONFERENCE,
    Publication.Form.BOOK_CHAPTER,
    Publication.Form.REVIEW_ARTICLE,
}
IP_TYPES: dict[str, str] = {
    "patent": IntellectualProperty.Kind.PATENT,
    "trademark": IntellectualProperty.Kind.TRADEMARK,
    "license": IntellectualProperty.Kind.OTHER,
    "registered-copyright": IntellectualProperty.Kind.OTHER,
    "disclosure": IntellectualProperty.Kind.OTHER,
    "invention": IntellectualProperty.Kind.OTHER,
}


def affiliation_items(record: Any, section: str) -> list[dict[str, Any]]:
    """Flatten ``activities-summary.<section>.affiliation-group[].summaries[]``."""
    items: list[dict[str, Any]] = []
    for group in dig(record, "activities-summary", section, "affiliation-group") or []:
        for summary in dig(group, "summaries") or []:
            for value in summary.values() if isinstance(summary, dict) else []:
                if isinstance(value, dict) and "put-code" in value:
                    items.append(value)
    return items


def choose_summary(summaries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One work summary per group: the first, unless a later one comes from a client
    (Crossref, Scopus, ...) while the first was typed in by the record holder."""
    if not summaries:
        return None
    first = summaries[0]
    if dig(first, "source", "source-client-id") is None:
        for candidate in summaries[1:]:
            if dig(candidate, "source", "source-client-id") is not None:
                return candidate
    return first


def work_summaries(record: Any) -> list[dict[str, Any]]:
    chosen = []
    for group in dig(record, "activities-summary", "works", "group") or []:
        summary = choose_summary(
            [s for s in dig(group, "work-summary") or [] if isinstance(s, dict)]
        )
        if summary is not None:
            chosen.append(summary)
    return chosen


def map_person(record: Any, imported: Imported) -> None:
    person = dig(record, "person") or {}
    imported.profile["first_name"] = text(person, "name", "given-names", "value")
    imported.profile["last_name"] = text(person, "name", "family-name", "value")
    imported.profile["bio"] = text(person, "biography", "content")
    emails = [text(e, "email") for e in dig(person, "emails", "email") or []]
    imported.profile["secondary_email"] = next((e for e in emails if e), "")
    countries = [text(a, "country", "value") for a in dig(person, "addresses", "address") or []]
    imported.profile["country_of_activity"] = next((c for c in countries if c), "")
    urls = [
        {"name": text(u, "url-name"), "url": text(u, "url", "value")}
        for u in dig(person, "researcher-urls", "researcher-url") or []
    ]
    urls = [u for u in urls if u["url"]]
    imported.profile["homepage"] = urls[0]["url"] if urls else ""
    imported.person = {
        "credit_name": text(person, "name", "credit-name", "value"),
        "other_names": [text(o, "content") for o in dig(person, "other-names", "other-name") or []],
        "keywords": [text(k, "content") for k in dig(person, "keywords", "keyword") or []],
        "researcher_urls": urls,
        "external_identifiers": [
            {
                "type": text(i, "external-id-type"),
                "value": text(i, "external-id-value"),
                "url": text(i, "external-id-url", "value"),
            }
            for i in dig(person, "external-identifiers", "external-identifier") or []
        ],
    }


def map_employments(record: Any, imported: Imported) -> None:
    for item in affiliation_items(record, "employments"):
        name, department, _country = org_fields(item)
        title = text(item, "role-title")
        start, end = partial_date(dig(item, "start-date")), partial_date(dig(item, "end-date"))
        position = position_from(title)
        imported.add(
            "employment",
            {
                "orcid_put_code": item["put-code"],
                "employer": name,
                "department": department,
                "position": position,
                "other_position": title if position == Position.OTHER else "",
                "start_date": start,
                "end_date": end,
                "is_present": not end,
                "other_information": title if position != Position.OTHER else "",
            },
        )


def map_educations(record: Any, imported: Imported) -> None:
    for item in affiliation_items(record, "educations"):
        name, department, _country = org_fields(item)
        title = text(item, "role-title")
        start, end = partial_date(dig(item, "start-date")), partial_date(dig(item, "end-date"))
        if is_research_degree(title):
            kind = (
                ResearchEducation.Kind.LICENTIATE
                if has(title, "licentiate")
                else ResearchEducation.Kind.PHD
            )
            imported.add(
                "research_education",
                {
                    "orcid_put_code": item["put-code"],
                    "university": name,
                    "department": department,
                    "kind": kind,
                    "subject": title,
                    "degree_date": end or start,
                },
            )
        else:
            degree = degree_from(title)
            imported.add(
                "basic_education",
                {
                    "orcid_put_code": item["put-code"],
                    "university": name,
                    "department": department,
                    "year": year_of(dig(item, "end-date")) or year_of(dig(item, "start-date")),
                    "subject": title,
                    "degree": degree,
                    "other_degree": title if degree == BasicEducation.Degree.OTHER else "",
                },
            )


def merit_entry(item: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    name, department, _country = org_fields(item)
    title = text(item, "role-title")
    return {
        "orcid_put_code": item["put-code"],
        "title": prefix + ", ".join(p for p in (title, name) if p),
        "start_year": year_of(dig(item, "start-date")),
        "end_year": year_of(dig(item, "end-date")),
        "description": ", ".join(p for p in (department, text(item, "url", "value")) if p),
    }


def map_qualifications(record: Any, imported: Imported) -> None:
    for item in affiliation_items(record, "qualifications"):
        title = text(item, "role-title")
        if is_docent(title):
            name, department, _country = org_fields(item)
            imported.add(
                "docent",
                {
                    "orcid_put_code": item["put-code"],
                    "university": name,
                    "department": department,
                    "subject": title,
                    "year": year_of(dig(item, "end-date")) or year_of(dig(item, "start-date")),
                },
            )
        else:
            imported.add("merit", merit_entry(item))


def map_invited_positions(record: Any, imported: Imported) -> None:
    for item in affiliation_items(record, "invited-positions"):
        name, department, _country = org_fields(item)
        start, end = partial_date(dig(item, "start-date")), partial_date(dig(item, "end-date"))
        imported.add(
            "exchange",
            {
                "orcid_put_code": item["put-code"],
                "host": name,
                "department": department,
                "kind": ResearchExchange.Kind.INVITED_POSITION,
                "custom_kind": text(item, "role-title"),
                "start_date": start,
                "end_date": end,
                "months": months_between(start, end),
            },
        )


def map_distinctions(record: Any, imported: Imported) -> None:
    for item in affiliation_items(record, "distinctions"):
        name, _department, country = org_fields(item)
        imported.add(
            "award",
            {
                "orcid_put_code": item["put-code"],
                "year": year_of(dig(item, "start-date")),
                "country": country,
                "award": text(item, "role-title") or name,
                "issuer": name,
            },
        )


def map_memberships_services(record: Any, imported: Imported) -> None:
    for section, prefix in (("memberships", "Member: "), ("services", "Service: ")):
        for item in affiliation_items(record, section):
            imported.add("merit", merit_entry(item, prefix))


def map_fundings(record: Any, imported: Imported, owner: str) -> None:
    for group in dig(record, "activities-summary", "fundings", "group") or []:
        for item in dig(group, "funding-summary") or []:
            if not isinstance(item, dict) or "put-code" not in item:
                continue
            name, _department, country = org_fields(item)
            ids = external_ids(item)
            imported.add(
                "grant",
                {
                    "orcid_put_code": item["put-code"],
                    "funder": name,
                    "country": country,
                    "applicant": owner,
                    "project_title": text(item, "title", "title", "value"),
                    "reference_number": ids[0]["value"] if ids else "",
                    "start_year": year_of(dig(item, "start-date")),
                    "end_year": year_of(dig(item, "end-date")),
                    "role": AwardedGrant.Role.APPLICANT,
                    "amount": int(float(text(item, "amount", "value") or 0)) or None,
                    "currency": text(item, "amount", "currency-code")[:3] or "SEK",
                },
            )


def map_peer_reviews(record: Any, imported: Imported) -> None:
    for group in dig(record, "activities-summary", "peer-reviews", "group") or []:
        for subgroup in dig(group, "peer-review-group") or []:
            for item in dig(subgroup, "peer-review-summary") or []:
                if not isinstance(item, dict) or "put-code" not in item:
                    continue
                org = text(item, "convening-organization", "name")
                role = text(item, "reviewer-role")
                year = year_of(dig(item, "completion-date"))
                imported.add(
                    "merit",
                    {
                        "orcid_put_code": item["put-code"],
                        "title": f"Peer review: {org}" + (f" ({role})" if role else ""),
                        "start_year": year,
                        "end_year": year,
                        "description": text(item, "review-group-id"),
                    },
                )


def contributors(work: Any, owner: str) -> tuple[list[str], list[str]]:
    """(authors, editors) from a full work; the record holder is the author of last resort."""
    first: list[str] = []
    authors: list[str] = []
    editors: list[str] = []
    for item in dig(work, "contributors", "contributor") or []:
        name = text(item, "credit-name", "value")
        if not name:
            continue
        role = text(item, "contributor-attributes", "contributor-role").lower()
        sequence = text(item, "contributor-attributes", "contributor-sequence").lower()
        if role == "editor":
            editors.append(name)
        elif role in ("", "author"):
            (first if sequence == "first" else authors).append(name)
    authors = first + authors
    if not authors and owner:
        authors = [owner]
    return authors, editors


def map_work(work: dict[str, Any], imported: Imported, owner: str) -> None:
    raw_type = text(work, "type").lower()
    title = text(work, "title", "title", "value")
    subtitle = text(work, "title", "subtitle", "value")
    date = partial_date(dig(work, "publication-date"))
    ids = external_ids(work)
    if raw_type in IP_TYPES:
        kind = IP_TYPES[raw_type]
        imported.add(
            "ip",
            {
                "orcid_put_code": work["put-code"],
                "kind": kind,
                "other_kind": raw_type if kind == IntellectualProperty.Kind.OTHER else "",
                "title": title,
                "number": ids[0]["value"] if ids else "",
                "date_approved": date,
            },
        )
        return
    form = WORK_FORMS.get(raw_type, Publication.Form.OTHER)
    doi = self_id(work, "doi")
    link = text(work, "url", "value") or (f"https://doi.org/{doi}" if doi else "")
    authors, editors = contributors(work, owner)
    imported.add(
        "publication",
        {
            "orcid_put_code": work["put-code"],
            "category": (
                Publication.Category.PEER_REVIEWED
                if form in PEER_REVIEWED_FORMS
                else Publication.Category.NOT_PEER_REVIEWED
            ),
            "form": form,
            "title": f"{title}: {subtitle}" if subtitle and subtitle not in title else title,
            "authors": authors,
            "editors": editors,
            "journal": text(work, "journal-title", "value"),
            "doi": doi,
            "isbn": self_id(work, "isbn"),
            "status": Publication.Status.PUBLISHED,
            "publication_date": date,
            "link": link[:512],
            "abstract": text(work, "short-description"),
            "orcid_work_type": raw_type[:50],
        },
    )


def map_record(record: dict[str, Any], works: list[dict[str, Any]]) -> Imported:
    """``record`` is ``/record``; ``works`` the full works of ``work_summaries(record)``."""
    imported = Imported(orcid=text(record, "orcid-identifier", "path"))
    map_person(record, imported)
    owner = f"{imported.profile['first_name']} {imported.profile['last_name']}".strip()
    map_employments(record, imported)
    map_educations(record, imported)
    map_qualifications(record, imported)
    map_invited_positions(record, imported)
    map_distinctions(record, imported)
    map_memberships_services(record, imported)
    map_fundings(record, imported, owner)
    map_peer_reviews(record, imported)
    for work in works:
        if isinstance(work, dict) and "put-code" in work:
            map_work(work, imported, owner)
    # research-resources are skipped: rare and without a CV section.
    return imported
