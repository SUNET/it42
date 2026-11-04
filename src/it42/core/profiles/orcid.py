"""ORCID iDs and the ORCID Public API v3.0 client.

Core only (org containers have no internet). Tests replace ``urlopen`` on this module.
"""

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class OrcidError(Exception):
    """A problem with an ORCID iD or the ORCID service, with a message for the user."""


def normalise_orcid(text: str) -> str:
    """Accept ``0000-0002-1825-0097`` or ``https://orcid.org/0000-0002-1825-0097``.

    Returns the bare iD or raises OrcidError (format and ISO 7064 mod 11-2 check digit).
    """
    value = text.strip().upper()
    value = re.sub(r"^(HTTPS?://)?(WWW\.)?(SANDBOX\.)?ORCID\.ORG/", "", value).strip("/")
    if not ORCID_RE.match(value):
        raise OrcidError("An ORCID iD looks like 0000-0002-1825-0097.")
    digits = value.replace("-", "")
    total = 0
    for char in digits[:-1]:
        total = (total + int(char)) * 2
    check = (12 - total % 11) % 11
    expected = "X" if check == 10 else str(check)
    if digits[-1] != expected:
        raise OrcidError(f"{value} is not a valid ORCID iD (wrong check digit).")
    return value


def validate_orcid(value: str) -> None:
    """Model/form validator wrapping ``normalise_orcid``."""
    if not value:
        return
    try:
        normalised = normalise_orcid(value)
    except OrcidError as exc:
        raise ValidationError(str(exc), code="invalid") from exc
    if normalised != value:
        raise ValidationError("Enter the bare ORCID iD, for example 0000-0002-1825-0097.")


# ---- Public API client -------------------------------------------------------------

UNREACHABLE = "ORCID is not reachable right now. Please try again later."


def _get(path: str) -> Any:
    url = f"{str(settings.ORCID_API_URL).rstrip('/')}/{path}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "it42-poc"})  # noqa: S310
    try:
        with urlopen(request, timeout=settings.ORCID_TIMEOUT) as response:  # noqa: S310
            return json.load(response)
    except HTTPError as exc:
        raise OrcidError(_http_message(exc)) from exc
    except (OSError, ValueError) as exc:  # URLError, timeouts, bad JSON
        raise OrcidError(UNREACHABLE) from exc


def _http_message(exc: HTTPError) -> str:
    if exc.code == 404:
        return "ORCID has no public record with that iD."
    if exc.code == 409:
        try:
            body = json.loads(exc.read().decode())
        except (ValueError, OSError):
            body = {}
        user = str(body.get("user-message") or "The ORCID record is deprecated or locked.")
        developer = str(body.get("developer-message") or "")
        others = re.findall(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", developer)
        hint = f" The primary record is {others[-1]}." if others else ""
        return f"{user}{hint}"
    return f"{UNREACHABLE} (HTTP {exc.code})"


def fetch_record(orcid: str) -> dict[str, Any]:
    """``/record`` for a public ORCID iD; follows ORCID's redirects for merged iDs."""
    record = _get(f"{orcid}/record")
    if not isinstance(record, dict):
        raise OrcidError(UNREACHABLE)
    return record


def fetch_works(
    orcid: str, put_codes: list[int], progress: Callable[[int, int], None] | None = None
) -> list[dict[str, Any]]:
    """Full works (contributors, citation, ...) in bulk, 100 per call, capped by settings.

    ``progress(done, total)`` is called before every call but the first, with the number
    of works requested so far and in all.
    """
    works: list[dict[str, Any]] = []
    codes = put_codes[: int(settings.ORCID_MAX_WORKS)]
    for start in range(0, len(codes), 100):
        if progress is not None and start:
            progress(start, len(codes))
        batch = ",".join(str(c) for c in codes[start : start + 100])
        bulk = _get(f"{orcid}/works/{batch}")
        for item in (bulk.get("bulk") or []) if isinstance(bulk, dict) else []:
            work = item.get("work") if isinstance(item, dict) else None
            if isinstance(work, dict):
                works.append(work)  # {"error": ...} items are skipped
    return works
