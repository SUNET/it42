"""The research organisation (RO) directory.

Universities and research institutes that can administer a grant are listed in a TOML
file maintained by the deployment's admins (``config/research_orgs.toml``, see the
``.example`` next to it). The same file is mounted read-only into every zone, so the core,
the FOs and the RO site agree on slugs and names without any directory events. Changing it
means editing the file and restarting the containers.

Each entry::

    [[org]]
    slug = "uu"                      # stable id, stored in answers and events
    name = "Uppsala University"
    kind = "university"              # or "research_institute"
    country = "SE"
    org_number = "202100-2932"
    website = "https://www.uu.se"
    admin_email = "admin@uu.example" # the RO's admin on ro.it42.vr, bound at login
    active = true                    # inactive orgs cannot be chosen any more
"""

import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from django.conf import settings

KINDS = {"university": "University", "research_institute": "Research institute"}
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
KEYS = {"slug", "name", "kind", "country", "org_number", "website", "admin_email", "active"}


class DirectoryError(ValueError):
    pass


@dataclass(frozen=True)
class ResearchOrg:
    slug: str
    name: str
    kind: str
    country: str
    org_number: str
    website: str
    admin_email: str
    active: bool

    @property
    def kind_label(self) -> str:
        return KINDS[self.kind]


def _text(raw: dict[str, object], key: str, index: int, required: bool = True) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str) or len(value) > 200 or (required and not value.strip()):
        raise DirectoryError(f"org {index}: {key} must be a string of 1-200 characters")
    return value.strip()


def parse(text: str) -> dict[str, ResearchOrg]:
    """The directory as slug -> ResearchOrg, in file order. Raises DirectoryError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DirectoryError(f"not valid TOML: {exc}") from exc
    entries = data.get("org", [])
    if not isinstance(entries, list):
        raise DirectoryError("use [[org]] tables")
    orgs: dict[str, ResearchOrg] = {}
    admins: set[str] = set()
    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            raise DirectoryError(f"org {index} must be a table")
        unknown = set(raw) - KEYS
        if unknown:
            raise DirectoryError(f"org {index} has unknown keys: {', '.join(sorted(unknown))}")
        slug = _text(raw, "slug", index)
        if not SLUG_RE.match(slug):
            raise DirectoryError(f"org {index}: slug must be 2-32 lowercase letters, digits, -")
        if slug in orgs:
            raise DirectoryError(f"org {index}: slug {slug!r} is listed twice")
        kind = _text(raw, "kind", index)
        if kind not in KINDS:
            raise DirectoryError(f"org {index}: kind must be one of {', '.join(KINDS)}")
        admin_email = _text(raw, "admin_email", index).lower()
        if not EMAIL_RE.match(admin_email):
            raise DirectoryError(f"org {index}: admin_email is not an email address")
        if admin_email in admins:
            raise DirectoryError(f"org {index}: {admin_email} is already another org's admin")
        admins.add(admin_email)
        active = raw.get("active", True)
        if not isinstance(active, bool):
            raise DirectoryError(f"org {index}: active must be true or false")
        orgs[slug] = ResearchOrg(
            slug=slug,
            name=_text(raw, "name", index),
            kind=kind,
            country=_text(raw, "country", index, required=False),
            org_number=_text(raw, "org_number", index, required=False),
            website=_text(raw, "website", index, required=False),
            admin_email=admin_email,
            active=active,
        )
    return orgs


@cache
def directory() -> dict[str, ResearchOrg]:
    """The directory of ``settings.RESEARCH_ORGS_FILE``, read once per process."""
    path = Path(settings.RESEARCH_ORGS_FILE)
    try:
        text = path.read_text()
    except OSError as exc:
        raise DirectoryError(f"cannot read {path}: {exc}") from exc
    return parse(text)


def get(slug: str) -> ResearchOrg | None:
    return directory().get(slug)


def active() -> list[ResearchOrg]:
    """Organisations applicants can choose, by name."""
    return sorted((o for o in directory().values() if o.active), key=lambda o: o.name)


def choices() -> list[tuple[str, str]]:
    return [(o.slug, o.name) for o in active()]


def name_of(slug: str) -> str:
    """Display name for a slug; unknown slugs are shown as they are."""
    org = get(slug)
    return org.name if org else slug


def administered_by(email: str) -> ResearchOrg | None:
    """The organisation whose admin_email this is (case-insensitive)."""
    email = email.strip().lower()
    return next((o for o in directory().values() if email and o.admin_email == email), None)
