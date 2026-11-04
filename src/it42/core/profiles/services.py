"""ORCID import into a researcher profile.

Rules:
- Profile scalars are filled only when empty; ``orcid_person`` is always replaced.
- An imported entry is matched by its ORCID put-code. Untouched imports (``source=orcid``)
  are updated in place, edited imports (``orcid_edited``) are skipped, hand-entered
  entries have no put-code and are never read or written.
- An import runs in the background (``importer.py``) and is staged first: ``stage_items``
  compares the mapped record with the CV, the researcher reviews the items and
  ``apply_review`` writes the included ones. Items edited during the review are saved as
  ``orcid_edited``.
- Every HTTP call happens before the transaction opens.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import CVEntry, OrcidImport, Profile, Source
from .orcid import fetch_record, fetch_works, normalise_orcid
from .orcid_mapping import Imported, map_record, work_summaries
from .sections import SECTIONS

PROFILE_FIELDS = (
    "first_name",
    "last_name",
    "bio",
    "secondary_email",
    "country_of_activity",
    "homepage",
)


@dataclass
class SectionCount:
    added: int = 0
    updated: int = 0
    skipped: int = 0


@dataclass
class ImportSummary:
    orcid: str
    counts: dict[str, SectionCount] = field(default_factory=dict)
    filled: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)

    def message(self) -> str:
        parts = []
        for key, count in self.counts.items():
            section = SECTIONS[key]
            bits = [f"{count.added} added"]
            if count.updated:
                bits.append(f"{count.updated} updated")
            if count.skipped:
                bits.append(f"{count.skipped} kept as edited")
            parts.append(f"{section.title.lower()}: {', '.join(bits)}")
        text = f"Imported {self.orcid}. " + ("; ".join(parts) + "." if parts else "No CV data.")
        if self.filled:
            text += " Filled " + ", ".join(f.replace("_", " ") for f in self.filled) + "."
        if self.areas:
            text += " Added research areas: " + ", ".join(self.areas) + "."
        return text


def _apply_section(
    key: str,
    items: list[dict[str, object]],
    profile: Profile,
    edited: Collection[int] = (),
) -> SectionCount:
    model = SECTIONS[key].model
    count = SectionCount()
    existing: dict[int, CVEntry] = {
        int(e.orcid_put_code): e
        for e in model.objects.filter(profile=profile, orcid_put_code__isnull=False)
        if e.orcid_put_code is not None
    }
    last = model.objects.filter(profile=profile).order_by("-sort_order").first()
    next_order = last.sort_order + 1 if last else 0
    seen: set[int] = set()
    for item in items:
        put_code = int(str(item["orcid_put_code"]))
        if put_code in seen:
            continue
        seen.add(put_code)
        fields = {k: v for k, v in item.items() if k != "orcid_put_code"}
        source = Source.ORCID_EDITED if put_code in edited else Source.ORCID
        current = existing.get(put_code)
        if current is None:
            model.objects.create(
                profile=profile,
                source=source,
                orcid_put_code=put_code,
                sort_order=next_order,
                **fields,
            )
            next_order += 1
            count.added += 1
        elif current.source == Source.ORCID:
            # An item edited in the review is protected from now on, even when the
            # researcher's version equals what is stored.
            changed = [k for k, v in fields.items() if getattr(current, k) != v]
            if changed or source != current.source:
                for name in changed:
                    setattr(current, name, fields[name])
                current.source = source
                current.save()
                count.updated += 1
        else:
            count.skipped += 1
    return count


def add_research_areas(profile: Profile, areas: list[str]) -> list[str]:
    """Append ``areas`` not already on the profile (case-insensitive); returns the new ones."""
    known = {a.casefold() for a in profile.research_areas}
    added = []
    for area in areas:
        area = area.strip()
        if area and area.casefold() not in known:
            known.add(area.casefold())
            added.append(area)
    profile.research_areas = [*profile.research_areas, *added]
    return added


def apply_import(
    profile: Profile,
    imported: Imported,
    *,
    edited: Collection[int] = (),
    areas: list[str] | None = None,
) -> ImportSummary:
    """Write a mapped record to the database (no network).

    ``edited`` are put-codes the researcher changed during review; ``areas`` research
    areas to add.
    """
    summary = ImportSummary(orcid=imported.orcid)
    with transaction.atomic():
        profile = Profile.objects.select_for_update().get(pk=profile.pk)
        for name in PROFILE_FIELDS:
            value = imported.profile.get(name)
            if value and not getattr(profile, name):
                setattr(profile, name, value)
                summary.filled.append(name)
        summary.areas = add_research_areas(profile, areas or [])
        profile.orcid = imported.orcid
        profile.orcid_person = imported.person
        profile.orcid_imported_at = timezone.now()
        profile.save()
        for key in SECTIONS:
            items = imported.entries.get(key)
            if items:
                summary.counts[key] = _apply_section(key, items, profile, edited)
    return summary


def fetch_import(text: str, report: Callable[[str, int], None] | None = None) -> Imported:
    """Fetch and map a public ORCID record (network only); raises OrcidError.

    ``report(stage, progress)`` is called as the work goes on (the background runner
    saves it for the loader dialog; see importer.STAGES).
    """

    def step(stage: str, progress: int) -> None:
        if report is not None:
            report(stage, progress)

    orcid = normalise_orcid(text)
    record = fetch_record(orcid)
    actual = str(record.get("orcid-identifier", {}).get("path") or orcid)
    put_codes = [int(s["put-code"]) for s in work_summaries(record)]
    step("fetching", 25)
    works = (
        fetch_works(
            actual, put_codes, lambda done, total: step("fetching", 25 + 45 * done // total)
        )
        if put_codes
        else []
    )
    step("reading", 75)
    imported = map_record(record, works)
    imported.orcid = actual
    return imported


def import_orcid(profile: Profile, text: str) -> ImportSummary:
    """Fetch a public ORCID record and merge it into ``profile`` without a review."""
    return apply_import(profile, fetch_import(text))


def clear_orcid(profile: Profile) -> int:
    """Delete untouched imports (``source=orcid``) in every section; edited ones stay."""
    deleted = 0
    with transaction.atomic():
        for section in SECTIONS.values():
            count, _ = section.model.objects.filter(profile=profile, source=Source.ORCID).delete()
            deleted += count
    return deleted


# Staging and review -------------------------------------------------------------------


def describe(key: str, fields: dict[str, Any]) -> dict[str, str]:
    """Summary, details and dates of an unsaved entry, for the review rows."""
    entry = SECTIONS[key].model(**fields)
    return {"summary": entry.summary(), "details": entry.details(), "dates": entry.dates()}


def stage_items(profile: Profile, imported: Imported) -> list[dict[str, Any]]:
    """Compare a mapped record with the CV; one review item per mapped entry.

    Item: ``n`` (index), ``section``, ``put_code``, ``fields``, ``summary``, ``details``,
    ``dates``, ``state`` (``new``, ``update`` for an untouched import ORCID changed,
    ``on_cv`` for unchanged or edited entries, which an import never touches), ``note``,
    ``include`` (new and update items start included) and ``edited``.
    """
    items: list[dict[str, Any]] = []
    for key, section in SECTIONS.items():
        existing = {
            int(e.orcid_put_code): e
            for e in section.model.objects.filter(profile=profile, orcid_put_code__isnull=False)
            if e.orcid_put_code is not None
        }
        seen: set[int] = set()
        for entry in imported.entries.get(key, []):
            put_code = int(str(entry["orcid_put_code"]))
            if put_code in seen:
                continue
            seen.add(put_code)
            fields = {k: v for k, v in entry.items() if k != "orcid_put_code"}
            current = existing.get(put_code)
            if current is None:
                state, note = "new", ""
            elif current.source != Source.ORCID:
                state, note = "on_cv", "Kept as you edited it"
            elif any(getattr(current, k) != v for k, v in fields.items()):
                state, note = "update", "Changed on ORCID"
            else:
                state, note = "on_cv", "On your CV"
            items.append(
                {
                    "n": len(items),
                    "section": key,
                    "put_code": put_code,
                    "fields": fields,
                    **describe(key, fields),
                    "state": state,
                    "note": note,
                    "include": state != "on_cv",
                    "edited": False,
                }
            )
    return items


def propose_areas(profile: Profile, person: dict[str, Any]) -> list[dict[str, Any]]:
    """ORCID keywords that are not research areas yet, all proposed as included."""
    known = {a.casefold() for a in profile.research_areas}
    proposed: list[dict[str, Any]] = []
    for keyword in person.get("keywords") or []:
        text = str(keyword).strip()[:100]
        if text and text.casefold() not in known:
            known.add(text.casefold())
            proposed.append({"text": text, "include": True})
    return proposed


def apply_review(job: OrcidImport) -> ImportSummary:
    """Write the included items of a reviewed import and mark it applied.

    The decisions are read from the locked row, so a change saved in another tab just
    before Done is the one that counts.
    """
    with transaction.atomic():
        locked = OrcidImport.objects.select_for_update().get(pk=job.pk)
        if locked.status != OrcidImport.Status.REVIEW:
            raise ValueError("This import is not waiting for a review.")
        imported = Imported(orcid=locked.orcid, profile=locked.profile_fields, person=locked.person)
        edited: set[int] = set()
        for item in locked.items:
            if item["include"] and item["state"] != "on_cv":
                fields = {"orcid_put_code": item["put_code"], **item["fields"]}
                imported.add(item["section"], fields)
                if item["edited"]:
                    edited.add(int(item["put_code"]))
        areas = [k["text"] for k in locked.keywords if k["include"]]
        summary = apply_import(locked.profile, imported, edited=edited, areas=areas)
        locked.status = OrcidImport.Status.APPLIED
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "finished_at", "updated_at"])
    return summary
