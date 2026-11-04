"""ORCID iD rules, the record mapper, the import service and the panel views.

The Public API is never called: ``orcid.urlopen`` is replaced by a fake that serves the
fixtures (``orcid_record.json`` is ORCID's demo record 0000-0002-1825-0097; ``orcid_works.json``
is a handmade bulk works answer with an error item, a patent and contributor edge cases).
"""

import copy
import io
import json
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from it42.core.accounts.models import User
from it42.core.profiles import importer, orcid
from it42.core.profiles.models import (
    Employment,
    IntellectualProperty,
    OrcidImport,
    OtherMerit,
    Profile,
    Publication,
    Source,
)
from it42.core.profiles.orcid import OrcidError, normalise_orcid, validate_orcid
from it42.core.profiles.orcid_mapping import map_record, partial_date, work_summaries
from it42.core.profiles.sections import SECTIONS
from it42.core.profiles.services import (
    apply_import,
    apply_review,
    clear_orcid,
    fetch_import,
    import_orcid,
)

FIXTURES = Path(__file__).parent / "fixtures"
DEMO = "0000-0002-1825-0097"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def record() -> dict[str, Any]:
    return load("orcid_record.json")


@pytest.fixture
def works() -> dict[str, Any]:
    return load("orcid_works.json")


class FakeApi:
    """Serves ``/record`` and ``/works/...`` from in-memory documents."""

    def __init__(self, record: dict[str, Any], works: dict[str, Any]) -> None:
        self.record = record
        self.works = works
        self.calls: list[str] = []

    def __call__(self, request: Any, timeout: float = 0) -> io.BytesIO:
        url = request.full_url
        self.calls.append(url)
        if url.endswith("/record"):
            return io.BytesIO(json.dumps(self.record).encode())
        if "/works/" in url:
            return io.BytesIO(json.dumps(self.works).encode())
        raise HTTPError(url, 404, "Not Found", Message(), io.BytesIO(b"{}"))


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, record: dict[str, Any], works: dict[str, Any]) -> FakeApi:
    fake = FakeApi(record, works)
    monkeypatch.setattr(orcid, "urlopen", fake)
    return fake


@pytest.fixture
def profile(a2: User) -> Profile:
    return Profile.objects.create(user=a2, first_name="Ulla")


# ---- iDs -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [DEMO, f"https://orcid.org/{DEMO}", f"http://orcid.org/{DEMO}/", f"  {DEMO} "],
)
def test_normalise_accepts_bare_and_url_forms(text: str) -> None:
    assert normalise_orcid(text) == DEMO


def test_normalise_accepts_x_check_digit_and_uppercases() -> None:
    assert normalise_orcid("0000-0002-9079-593x") == "0000-0002-9079-593X"


@pytest.mark.parametrize("text", ["0000-0002-1825-0098", "0000-0002-1825-009", "nope", ""])
def test_normalise_rejects_bad_ids(text: str) -> None:
    with pytest.raises(OrcidError):
        normalise_orcid(text)


def test_model_validator_wants_the_bare_id() -> None:
    validate_orcid("")
    validate_orcid(DEMO)
    with pytest.raises(ValidationError):
        validate_orcid(f"https://orcid.org/{DEMO}")
    with pytest.raises(ValidationError):
        validate_orcid("0000-0002-1825-0098")


# ---- mapper --------------------------------------------------------------------------


def test_work_summaries_prefer_client_sources(record: dict[str, Any]) -> None:
    codes = [s["put-code"] for s in work_summaries(record)]
    assert codes == [9543020, 4562455, 4562454, 4562453, 4562456, 19980729]


def test_map_record_demo(record: dict[str, Any], works: dict[str, Any]) -> None:
    imported = map_record(record, [w["work"] for w in works["bulk"] if "work" in w])
    assert imported.orcid == DEMO
    assert imported.profile["first_name"] == "Josiah"
    assert imported.profile["last_name"] == "Carberry"
    assert imported.profile["bio"].startswith("Josiah Carberry is a fictitious person")
    assert imported.profile["homepage"] == "http://library.brown.edu/about/hay/carberry.php"
    assert imported.profile["secondary_email"] == ""
    assert imported.person["keywords"] == ["psychoceramics", "ionian philology"]
    assert imported.person["other_names"][0] == "Josiah Stinkney Carberry"
    assert imported.person["external_identifiers"][0]["type"] == "Scopus Author ID"
    assert {k: len(v) for k, v in imported.entries.items()} == {
        "employment": 2,
        "merit": 1,
        "ip": 1,
        "publication": 4,
    }
    wesleyan = imported.entries["employment"][0]
    assert wesleyan["orcid_put_code"] == 4288
    assert wesleyan["employer"] == "Wesleyan University"
    assert wesleyan["department"] == "Psychoceramics"
    assert wesleyan["position"] == "professor"
    assert wesleyan["start_date"] == "1930-02"  # 29 Feb 1930 does not exist: day dropped
    assert wesleyan["is_present"] is True
    review = imported.entries["merit"][0]
    assert review["title"] == "Peer review: The Psychoceramics Society (reviewer)"
    assert review["start_year"] == 2004
    assert review["description"] == "issn:1234-5678"
    patent = imported.entries["ip"][0]
    assert patent["kind"] == "patent" and patent["number"] == "US1234567"
    assert patent["date_approved"] == "2011"


def test_map_work_contributors_and_fallbacks(record: dict[str, Any], works: dict[str, Any]) -> None:
    imported = map_record(record, [w["work"] for w in works["bulk"] if "work" in w])
    by_code = {p["orcid_put_code"]: p for p in imported.entries["publication"]}
    article = by_code[9543020]
    assert article["authors"] == ["Josiah Carberry", "Ann Other"]  # first; null name skipped
    assert article["editors"] == ["Ed Itor"]
    assert article["doi"] == "10.5555/12345680"
    assert article["link"] == "https://doi.org/10.5555/12345680"
    assert article["journal"] == "Journal of Psychoceramics"
    assert article["publication_date"] == "2008-11"
    assert article["category"] == "peer_reviewed" and article["form"] == "journal_article"
    assert article["abstract"] == "An abstract."
    assert article["title"].startswith("A Methodology for the Emulation of Architecture: ")
    chapter = by_code[4562454]
    assert chapter["authors"] == ["Josiah Carberry"]  # record holder as sole author
    assert chapter["form"] == "book_chapter"
    software = by_code[4562456]
    assert software["form"] == "software" and software["category"] == "not_peer_reviewed"
    assert software["link"] == "https://example.org/kiln"
    assert software["publication_date"] == ""
    assert 4562453 not in by_code  # the bulk error item


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"year": {"value": "2012"}, "month": {"value": "03"}, "day": {"value": "05"}},
            "2012-03-05",
        ),
        ({"year": {"value": "2012"}, "month": {"value": "3"}, "day": None}, "2012-03"),
        ({"year": {"value": "2012"}, "month": None, "day": {"value": "05"}}, "2012"),
        ({"year": {"value": "1930"}, "month": {"value": "02"}, "day": {"value": "29"}}, "1930-02"),
        ({"year": {"value": "2012"}, "month": {"value": "13"}, "day": None}, "2012"),
        (None, ""),
    ],
)
def test_partial_date_mapping(raw: Any, expected: str) -> None:
    assert partial_date(raw) == expected


def test_map_affiliations_by_keyword() -> None:
    def item(section: str, title: str, put: int, end: Any = None) -> dict[str, Any]:
        summary = {
            "put-code": put,
            "role-title": title,
            "department-name": "Dept",
            "organization": {"name": "Uni", "address": {"country": "SE"}},
            "start-date": {"year": {"value": "2001"}, "month": {"value": "09"}},
            "end-date": end,
        }
        return {"affiliation-group": [{"summaries": [{f"{section}-summary": summary}]}]}

    record = {
        "orcid-identifier": {"path": DEMO},
        "person": {"name": {"given-names": {"value": "A"}, "family-name": {"value": "B"}}},
        "activities-summary": {
            "educations": {
                **item("education", "PhD in Chemistry", 1, {"year": {"value": "2006"}}),
            },
            "qualifications": item("qualification", "Docent in Physics", 2),
            "invited-positions": item(
                "invited-position",
                "Visiting fellow",
                3,
                {"year": {"value": "2002"}, "month": {"value": "03"}},
            ),
            "distinctions": item("distinction", "Best paper", 4),
            "memberships": item("membership", "Member", 5),
            "fundings": {
                "group": [
                    {
                        "funding-summary": [
                            {
                                "put-code": 6,
                                "title": {"title": {"value": "Project X"}},
                                "organization": {"name": "VR", "address": {"country": "SE"}},
                                "external-ids": {
                                    "external-id": [
                                        {
                                            "external-id-type": "grant_number",
                                            "external-id-value": "2020-1",
                                        }
                                    ]
                                },
                                "start-date": {"year": {"value": "2020"}},
                                "end-date": {"year": {"value": "2023"}},
                            }
                        ]
                    }
                ]
            },
        },
    }
    imported = map_record(record, [])
    phd = imported.entries["research_education"][0]
    assert phd["kind"] == "phd" and phd["degree_date"] == "2006" and phd["university"] == "Uni"
    assert imported.entries["docent"][0]["subject"] == "Docent in Physics"
    exchange = imported.entries["exchange"][0]
    assert exchange["kind"] == "invited_position" and exchange["months"] == 6
    award = imported.entries["award"][0]
    assert award["award"] == "Best paper" and award["issuer"] == "Uni" and award["year"] == 2001
    assert imported.entries["merit"][0]["title"] == "Member: Member, Uni"
    grant = imported.entries["grant"][0]
    assert grant["project_title"] == "Project X" and grant["reference_number"] == "2020-1"
    assert grant["applicant"] == "A B" and grant["end_year"] == 2023


# ---- import service -------------------------------------------------------------------


def manual_employment(profile: Profile) -> Employment:
    return Employment.objects.create(
        profile=profile, employer="KTH", position="researcher", start_date="2015", is_present=True
    )


def test_import_fills_empty_fields_and_adds_entries(api: FakeApi, profile: Profile) -> None:
    manual = manual_employment(profile)
    summary = import_orcid(profile, f"https://orcid.org/{DEMO}")
    assert [c.added for c in summary.counts.values()] == [2, 1, 1, 4]
    assert "employments: 2 added" in summary.message()
    profile.refresh_from_db()
    assert profile.first_name == "Ulla"  # not overwritten
    assert profile.last_name == "Carberry"  # filled
    assert profile.orcid == DEMO and profile.orcid_imported_at is not None
    assert profile.orcid_person["keywords"] == ["psychoceramics", "ionian philology"]
    manual.refresh_from_db()
    assert manual.employer == "KTH" and manual.source == Source.MANUAL and manual.sort_order == 0
    imported = list(Employment.objects.filter(profile=profile, source=Source.ORCID))
    assert [e.sort_order for e in imported] == [1, 2]  # after the manual entry
    assert Publication.objects.filter(profile=profile).count() == 4
    assert IntellectualProperty.objects.get(profile=profile).number == "US1234567"
    assert OtherMerit.objects.get(profile=profile).title.startswith("Peer review")
    assert [u for u in api.calls if "/works/" in u] == [
        f"https://pub.orcid.org/v3.0/{DEMO}/works/9543020,4562455,4562454,4562453,4562456,19980729"
    ]


def test_reimport_is_idempotent_then_updates_untouched(api: FakeApi, profile: Profile) -> None:
    import_orcid(profile, DEMO)
    again = import_orcid(profile, DEMO)
    assert all(c.added == 0 and c.updated == 0 and c.skipped == 0 for c in again.counts.values())
    assert Employment.objects.filter(profile=profile).count() == 2
    api.record = copy.deepcopy(api.record)
    group = api.record["activities-summary"]["employments"]["affiliation-group"][0]
    group["summaries"][0]["employment-summary"]["department-name"] = "Ceramics"
    third = import_orcid(profile, DEMO)
    assert third.counts["employment"].updated == 1
    assert Employment.objects.get(profile=profile, orcid_put_code=4288).department == "Ceramics"


def test_edited_imports_are_protected(api: FakeApi, profile: Profile) -> None:
    import_orcid(profile, DEMO)
    entry = Employment.objects.get(profile=profile, orcid_put_code=4288)
    entry.department = "My own words"
    entry.source = Source.ORCID_EDITED
    entry.save()
    api.record = copy.deepcopy(api.record)
    group = api.record["activities-summary"]["employments"]["affiliation-group"][0]
    group["summaries"][0]["employment-summary"]["department-name"] = "Ceramics"
    summary = import_orcid(profile, DEMO)
    assert summary.counts["employment"].skipped == 1
    assert "1 kept as edited" in summary.message()
    entry.refresh_from_db()
    assert entry.department == "My own words"


def test_clear_removes_only_untouched_imports(api: FakeApi, profile: Profile) -> None:
    manual = manual_employment(profile)
    import_orcid(profile, DEMO)
    edited = Employment.objects.get(profile=profile, orcid_put_code=4288)
    edited.source = Source.ORCID_EDITED
    edited.save()
    assert clear_orcid(profile) == 2 + 1 + 1 + 4 - 1  # all imports but the edited one
    remaining = set(Employment.objects.filter(profile=profile).values_list("pk", flat=True))
    assert remaining == {manual.pk, edited.pk}
    assert not Publication.objects.filter(profile=profile).exists()


def http_error(code: int, body: dict[str, Any]) -> Callable[..., Any]:
    def fake(request: Any, timeout: float = 0) -> Any:
        raise HTTPError(
            request.full_url, code, "x", Message(), io.BytesIO(json.dumps(body).encode())
        )

    return fake


def test_errors_write_nothing(monkeypatch: pytest.MonkeyPatch, profile: Profile) -> None:
    deprecated = {
        "user-message": "The ORCID record is deprecated.",
        "developer-message": "409 Conflict: deprecated, primary record https://orcid.org/0000-0001-5109-3700",
    }
    cases: list[tuple[Callable[..., Any], str]] = [
        (http_error(404, {}), "no public record"),
        (http_error(409, deprecated), "primary record is 0000-0001-5109-3700"),
        (http_error(500, {}), "not reachable"),
    ]

    def timeout(request: Any, timeout: float = 0) -> Any:
        raise URLError("timed out")

    def garbage(request: Any, timeout: float = 0) -> Any:
        return io.BytesIO(b"<html>")

    cases += [(timeout, "not reachable"), (garbage, "not reachable")]
    for fake, expected in cases:
        monkeypatch.setattr(orcid, "urlopen", fake)
        with pytest.raises(OrcidError, match=expected):
            import_orcid(profile, DEMO)
    profile.refresh_from_db()
    assert profile.orcid == "" and profile.orcid_imported_at is None
    assert not Employment.objects.filter(profile=profile).exists()


def test_bulk_works_are_fetched_in_batches_and_capped(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    calls: list[str] = []

    def fake(request: Any, timeout: float = 0) -> io.BytesIO:
        calls.append(request.full_url)
        codes = request.full_url.rsplit("/", 1)[1].split(",")
        return io.BytesIO(
            json.dumps({"bulk": [{"work": {"put-code": int(c)}} for c in codes]}).encode()
        )

    monkeypatch.setattr(orcid, "urlopen", fake)
    settings.ORCID_MAX_WORKS = 150
    works = orcid.fetch_works(DEMO, list(range(1, 201)))
    assert len(calls) == 2 and len(works) == 150
    assert calls[0].endswith("/works/" + ",".join(str(i) for i in range(1, 101)))


# ---- background import and review ------------------------------------------------------


def start(client: Client, orcid_id: str = DEMO) -> OrcidImport:
    response = client.post("/profile/orcid/", {"orcid": orcid_id})
    assert response.status_code == 302 and response["Location"] == "/profile/"
    return OrcidImport.objects.latest("created_at")


def test_start_queues_without_fetching(api: FakeApi, u2_client: Client) -> None:
    job = start(u2_client, f"https://orcid.org/{DEMO}")
    assert job.status == OrcidImport.Status.QUEUED and job.orcid == DEMO
    assert api.calls == []  # the request only queues; core-orcid fetches
    html = u2_client.get("/profile/").content.decode()
    assert "Importing your ORCID record" in html and "Waiting to start" in html
    assert f'data-orcid-import="/profile/orcid/{job.public_id}/status/"' in html
    assert 'http-equiv="refresh"' in html  # the no-JavaScript loader refreshes itself
    status = u2_client.get(f"/profile/orcid/{job.public_id}/status/").json()
    assert status == {"status": "queued", "stage": "Waiting to start…", "progress": 0, "error": ""}


def test_start_dialog_and_bad_id(u2_client: Client, a2: User) -> None:
    assert "Start import" in u2_client.get("/profile/orcid/").content.decode()
    html = u2_client.post("/profile/orcid/", {"orcid": "0000-0002-1825-0098"}).content.decode()
    assert "wrong check digit" in html
    assert not OrcidImport.objects.exists()


def test_one_active_import_per_profile(u2_client: Client) -> None:
    start(u2_client)
    response = u2_client.post("/profile/orcid/", {"orcid": DEMO}, follow=True)
    assert "already in progress" in response.content.decode()
    assert OrcidImport.objects.count() == 1


def test_runner_stages_the_record_and_writes_nothing(
    api: FakeApi, u2_client: Client, a2: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = Profile.objects.create(user=a2, first_name="Ulla")
    manual_employment(profile)
    job = start(u2_client)
    seen: list[tuple[str, int]] = []
    real = importer.report

    def spy(job: OrcidImport, stage: str, progress: int) -> None:
        seen.append((stage, progress))
        real(job, stage, progress)

    monkeypatch.setattr(importer, "report", spy)
    assert importer.run_pending() == 1
    assert [s for s, _ in seen] == ["fetching", "reading", "matching", "preparing"]
    assert [p for _, p in seen] == sorted(p for _, p in seen)
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.REVIEW and job.progress == 100
    assert {i["state"] for i in job.items} == {"new"}
    assert len(job.items) == 2 + 1 + 1 + 4
    assert [k["text"] for k in job.keywords] == ["psychoceramics", "ionian philology"]
    assert Employment.objects.filter(profile=profile).count() == 1  # only the manual one
    profile.refresh_from_db()
    assert profile.orcid == "" and profile.orcid_imported_at is None


def test_review_include_exclude_edit_and_done(api: FakeApi, u2_client: Client, a2: User) -> None:
    job = start(u2_client)
    importer.run_pending()
    html = u2_client.get("/profile/").content.decode()
    assert "Review your ORCID data" in html and "Wesleyan University" in html
    items = OrcidImport.objects.get(pk=job.pk).items
    wesleyan = next(i for i in items if i["put_code"] == 4288)
    patent = next(i for i in items if i["section"] == "ip")
    base = f"/profile/orcid/{job.public_id}"

    assert u2_client.post(f"{base}/item/{patent['n']}/", {"action": "exclude"}).status_code == 302
    edit_url = f"{base}/item/{wesleyan['n']}/edit/"
    assert "Edit before adding" in u2_client.get(edit_url).content.decode()
    fields = {**wesleyan["fields"], "department": "Ceramics, edited"}
    form = {k: v for k, v in fields.items() if v not in (None, False) and k != "orcid_work_type"}
    assert u2_client.post(edit_url, form).status_code == 302
    u2_client.post(f"{base}/keyword/1/")  # leave out "ionian philology"

    done = u2_client.post(f"{base}/done/", follow=True).content.decode()
    assert f"Imported {DEMO}" in done and "Added research areas: psychoceramics" in done
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.APPLIED
    entry = Employment.objects.get(profile__user=a2, orcid_put_code=4288)
    assert entry.department == "Ceramics, edited" and entry.source == Source.ORCID_EDITED
    assert not IntellectualProperty.objects.filter(profile__user=a2).exists()
    assert Publication.objects.filter(profile__user=a2).count() == 4
    profile = Profile.objects.get(user=a2)
    assert profile.orcid == DEMO and profile.research_areas == ["psychoceramics"]
    assert "Review your ORCID data" not in u2_client.get("/profile/").content.decode()


def test_second_import_marks_what_is_on_the_cv(api: FakeApi, u2_client: Client, a2: User) -> None:
    job = start(u2_client)
    importer.run_pending()
    u2_client.post(f"/profile/orcid/{job.public_id}/done/")
    entry = Employment.objects.get(profile__user=a2, orcid_put_code=4288)
    entry.source = Source.ORCID_EDITED
    entry.save()
    api.record["activities-summary"]["employments"]["affiliation-group"][0]["summaries"][0][
        "employment-summary"
    ]["department-name"] = "Changed"
    again = start(u2_client)
    importer.run_pending()
    again.refresh_from_db()
    states = {i["put_code"]: (i["state"], i["note"]) for i in again.items}
    assert states[4288] == ("on_cv", "Kept as you edited it")
    assert {s for s, _ in states.values()} == {"on_cv"}
    assert again.keywords == []  # already research areas
    html = u2_client.get("/profile/").content.decode()
    assert "On your CV" in html and "0 of 0 new or changed items will be added" in html


def test_cancel_while_running_and_discard_review(api: FakeApi, u2_client: Client, a2: User) -> None:
    job = start(u2_client)
    OrcidImport.objects.filter(pk=job.pk).update(status=OrcidImport.Status.RUNNING)
    u2_client.post(f"/profile/orcid/{job.public_id}/cancel/")
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.CANCELLED
    with pytest.raises(importer.Cancelled):
        importer.report(job, "fetching", 25)  # the runner stops at its next report

    second = start(u2_client)
    importer.run_pending()
    response = u2_client.post(f"/profile/orcid/{second.public_id}/cancel/", follow=True)
    assert "Nothing was changed" in response.content.decode()
    assert not Employment.objects.filter(profile__user=a2).exists()
    assert u2_client.post(f"/profile/orcid/{second.public_id}/done/").status_code == 302
    assert not Employment.objects.filter(profile__user=a2).exists()


def test_failure_is_shown_then_dismissed(
    monkeypatch: pytest.MonkeyPatch, u2_client: Client
) -> None:
    monkeypatch.setattr(orcid, "urlopen", http_error(404, {}))
    job = start(u2_client)
    importer.run_pending()
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.FAILED and "no public record" in job.error
    html = u2_client.get("/profile/").content.decode()
    assert "The import did not finish" in html and "Try again" in html
    u2_client.post(f"/profile/orcid/{job.public_id}/cancel/")
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.DISMISSED and "no public record" in job.error
    assert "The import did not finish" not in u2_client.get("/profile/").content.decode()


def test_requeue_running_after_a_restart(u2_client: Client) -> None:
    job = start(u2_client)
    OrcidImport.objects.filter(pk=job.pk).update(status=OrcidImport.Status.RUNNING, progress=50)
    assert importer.requeue_running() == 1
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.QUEUED and job.progress == 0


def test_import_views_require_login_and_post(client: Client, u2_client: Client) -> None:
    assert client.get("/profile/orcid/").status_code == 302
    job = start(u2_client)
    base = f"/profile/orcid/{job.public_id}"
    assert client.get(f"{base}/status/").status_code == 302
    for path in ("/cancel/", "/done/", "/item/0/", "/keyword/0/"):
        assert u2_client.get(base + path).status_code == 405


def test_import_is_isolated_per_user(
    api: FakeApi, u2_client: Client, make_user: Callable[..., User]
) -> None:
    other = make_user("a3")
    other_client = Client()
    other_client.force_login(other)
    job = start(u2_client)
    importer.run_pending()
    base = f"/profile/orcid/{job.public_id}"
    assert other_client.get(f"{base}/status/").status_code == 404
    assert other_client.post(f"{base}/done/").status_code == 404
    assert other_client.post(f"{base}/item/0/", {"action": "exclude"}).status_code == 404
    assert other_client.get(f"{base}/item/0/edit/").status_code == 404
    assert "Wesleyan" not in other_client.get("/profile/").content.decode()
    u2_client.post(f"{base}/done/")
    assert SECTIONS["employment"].model.objects.filter(profile__user=other).count() == 0
    cleared = u2_client.post("/profile/orcid/clear/", follow=True)
    assert "Removed 8 imported entries" in cleared.content.decode()


def test_runner_reports_alive_during_an_import(api: FakeApi, u2_client: Client) -> None:
    start(u2_client)
    beats: list[int] = []
    assert importer.run_pending(alive=lambda: beats.append(1)) == 1
    # Before the job and at every stage, not only once the queue is empty.
    assert len(beats) >= 5


def test_done_applies_the_decisions_stored_at_that_moment(
    api: FakeApi, u2_client: Client, a2: User
) -> None:
    job = start(u2_client)
    importer.run_pending()
    stale = OrcidImport.objects.get(pk=job.pk)  # e.g. the copy another tab holds
    patent = next(i for i in stale.items if i["section"] == "ip")
    u2_client.post(f"/profile/orcid/{job.public_id}/item/{patent['n']}/", {"action": "exclude"})
    apply_review(stale)
    assert not IntellectualProperty.objects.filter(profile__user=a2).exists()


def test_an_edit_equal_to_the_cv_still_protects_the_entry(api: FakeApi, profile: Profile) -> None:
    import_orcid(profile, DEMO)
    apply_import(profile, fetch_import(DEMO), edited={4288})  # same values, edited in review
    entry = Employment.objects.get(profile=profile, orcid_put_code=4288)
    assert entry.source == Source.ORCID_EDITED


def test_cancel_after_done_says_so(api: FakeApi, u2_client: Client, a2: User) -> None:
    job = start(u2_client)
    importer.run_pending()
    u2_client.post(f"/profile/orcid/{job.public_id}/done/")
    html = u2_client.post(f"/profile/orcid/{job.public_id}/cancel/", follow=True)
    assert "already added to your profile" in html.content.decode()
    assert "Nothing was changed" not in html.content.decode()
    job.refresh_from_db()
    assert job.status == OrcidImport.Status.APPLIED
