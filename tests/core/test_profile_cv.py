"""The researcher profile: details form, generic CV section views, ordering."""

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from django.utils.html import escape

from it42.core.accounts.models import User
from it42.core.applications.services import applicant_name
from it42.core.profiles.models import CVEntry, Employment, Profile, Publication, Source
from it42.core.profiles.sections import SECTIONS, Section

# A minimal valid POST body for every section (choice fields with defaults are still
# required by the ModelForm, so they are spelled out).
MINIMAL: dict[str, dict[str, Any]] = {
    "basic_education": {"university": "KTH", "degree": "master", "year": 2010},
    "research_education": {"university": "KTH", "kind": "phd", "degree_date": "2015-06"},
    "employment": {
        "employer": "KTH",
        "position": "researcher",
        "start_date": "2016",
        "is_present": "on",
    },
    "postdoc": {"host": "ETH", "start_date": "2015-09", "end_date": "2016-08", "months": 12},
    "exchange": {"host": "MIT", "kind": "research_visit", "start_date": "2018"},
    "interruption": {"start_date": "2019-01", "end_date": "2019-06", "description": "Leave"},
    "docent": {"university": "KTH", "subject": "Physics", "year": 2020},
    "supervision": {
        "kind": "individual",
        "role": "main_supervisor",
        "supervised_type": "phd",
        "first_name": "Sam",
        "last_name": "Svensson",
    },
    "grant": {"funder": "VR", "role": "applicant", "currency": "SEK", "amount": 1000000},
    "award": {"award": "Best thesis", "year": 2016},
    "merit": {"title": "Board member"},
    "ip": {"kind": "patent", "title": "Widget", "number": "SE1"},
    "publication": {
        "category": "peer_reviewed",
        "form": "journal_article",
        "status": "published",
        "title": "On widgets",
        "authors": "Ulla Svensson\nSam Svensson",
        "publication_date": "2021-03",
    },
}


@pytest.fixture(params=list(SECTIONS), ids=list(SECTIONS))
def section(request: pytest.FixtureRequest) -> Section:
    return SECTIONS[request.param]


def entries(section: Section, user: User) -> list[CVEntry]:
    return list(section.model.objects.filter(profile__user=user))


def add(client: Client, section: Section, **overrides: Any) -> Any:
    data = {**MINIMAL[section.key], **overrides}
    return client.post(f"/profile/cv/{section.key}/add/", data)


def test_sections_cover_every_minimal_body() -> None:
    assert list(MINIMAL) == list(SECTIONS)


def test_add_edit_delete(section: Section, u2_client: Client, a2: User) -> None:
    assert u2_client.get(f"/profile/cv/{section.key}/add/").status_code == 200
    response = add(u2_client, section)
    assert response.status_code == 302, response.content.decode()
    assert response["Location"] == f"/profile/data/#{section.key}"
    (entry,) = entries(section, a2)
    assert entry.source == Source.MANUAL and entry.sort_order == 0 and entry.summary()
    add(u2_client, section)
    assert [e.sort_order for e in entries(section, a2)] == [0, 1]

    page = u2_client.get("/profile/").content.decode()  # the Academic CV table
    assert escape(entry.summary()) in page
    assert f'data-section="{section.key}"' in page
    data = u2_client.get("/profile/data/").content.decode()  # the Edit data dialog
    assert escape(entry.summary()) in data and f'id="{section.key}"' in data

    edit_url = f"/profile/cv/{section.key}/{entry.pk}/edit/"
    assert u2_client.get(edit_url).status_code == 200
    assert u2_client.post(edit_url, MINIMAL[section.key]).status_code == 302
    entry.refresh_from_db()
    assert entry.source == Source.MANUAL

    assert u2_client.get(f"/profile/cv/{section.key}/{entry.pk}/delete/").status_code == 405
    assert u2_client.post(f"/profile/cv/{section.key}/{entry.pk}/delete/").status_code == 302
    assert len(entries(section, a2)) == 1


def test_entries_are_private(
    section: Section, u2_client: Client, a2: User, make_user: Callable[..., User]
) -> None:
    add(u2_client, section)
    (entry,) = entries(section, a2)
    other = Client()
    other.force_login(make_user("a3"))
    base = f"/profile/cv/{section.key}/{entry.pk}"
    assert other.get(f"{base}/edit/").status_code == 404
    assert other.post(f"{base}/edit/", MINIMAL[section.key]).status_code == 404
    assert other.post(f"{base}/delete/").status_code == 404
    assert other.post(f"{base}/move/", {"direction": "up"}).status_code == 404
    assert entry.summary() not in other.get("/profile/").content.decode()
    assert len(entries(section, a2)) == 1


def test_unknown_section_is_404(u2_client: Client) -> None:
    assert u2_client.get("/profile/cv/nope/add/").status_code == 404
    assert u2_client.post("/profile/cv/nope/reorder/", "{}", "application/json").status_code == 404


def test_editing_an_import_marks_it_edited(u2_client: Client, a2: User) -> None:
    add(u2_client, SECTIONS["employment"])
    entry = Employment.objects.get(profile__user=a2)
    entry.source = Source.ORCID
    entry.orcid_put_code = 4288
    entry.save()
    url = f"/profile/cv/employment/{entry.pk}/edit/"
    assert "came from ORCID" in u2_client.get(url).content.decode()
    u2_client.post(url, MINIMAL["employment"])  # unchanged: still an untouched import
    entry.refresh_from_db()
    assert entry.source == Source.ORCID
    u2_client.post(url, {**MINIMAL["employment"], "department": "Physics"})
    entry.refresh_from_db()
    assert entry.source == Source.ORCID_EDITED and entry.department == "Physics"
    assert entry.orcid_put_code == 4288


def test_move_and_reorder(u2_client: Client, a2: User) -> None:
    section = SECTIONS["merit"]
    for title in ("a", "b", "c"):
        add(u2_client, section, title=title)
    ids = [e.pk for e in entries(section, a2)]

    def order() -> list[int]:
        return [e.pk for e in entries(section, a2)]

    u2_client.post(f"/profile/cv/merit/{ids[2]}/move/", {"direction": "up"})
    assert order() == [ids[0], ids[2], ids[1]]
    u2_client.post(f"/profile/cv/merit/{ids[0]}/move/", {"direction": "up"})  # no-op at top
    assert order() == [ids[0], ids[2], ids[1]]
    u2_client.post(f"/profile/cv/merit/{ids[0]}/move/", {"direction": "down"})
    assert order() == [ids[2], ids[0], ids[1]]
    assert (
        u2_client.post(f"/profile/cv/merit/{ids[0]}/move/", {"direction": "sideways"}).status_code
        == 400
    )

    response = u2_client.post(
        "/profile/cv/merit/reorder/",
        json.dumps({"order": [ids[1], ids[0], ids[2]]}),
        "application/json",
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert order() == [ids[1], ids[0], ids[2]]
    assert [e.sort_order for e in entries(section, a2)] == [0, 1, 2]


def test_reorder_rejects_partial_or_foreign_lists(
    u2_client: Client, a2: User, make_user: Callable[..., User]
) -> None:
    section = SECTIONS["merit"]
    for title in ("a", "b"):
        add(u2_client, section, title=title)
    ids = [e.pk for e in entries(section, a2)]
    other = Client()
    other.force_login(make_user("a3"))
    add(other, section, title="theirs")
    (foreign,) = section.model.objects.filter(profile__user__sso_subject="a3")

    def post(body: Any) -> int:
        return u2_client.post("/profile/cv/merit/reorder/", body, "application/json").status_code

    assert post(json.dumps({"order": ids[:1]})) == 400
    assert post(json.dumps({"order": [*ids, foreign.pk]})) == 400
    assert post(json.dumps({"order": [ids[0], ids[0]]})) == 400
    assert post(json.dumps({"order": [ids[1], foreign.pk]})) == 400
    assert post("not json") == 400
    assert post(json.dumps({"nope": ids})) == 400
    assert [e.pk for e in entries(section, a2)] == ids
    assert post(json.dumps({"order": [ids[1], ids[0]]})) == 200


@pytest.mark.parametrize("bad", ["2012-13", "12-2012", "2012-1", "20120", "2012-02-30"])
def test_partial_dates_are_validated(u2_client: Client, a2: User, bad: str) -> None:
    response = add(u2_client, SECTIONS["employment"], start_date=bad)
    assert response.status_code == 200
    assert (
        "Enter a date as YYYY" in response.content.decode()
        or "not a real date" in response.content.decode()
    )
    assert not Employment.objects.filter(profile__user=a2).exists()


@pytest.mark.parametrize("good", ["2012", "2012-03", "2012-03-31"])
def test_partial_dates_accepted(u2_client: Client, a2: User, good: str) -> None:
    assert add(u2_client, SECTIONS["employment"], start_date=good).status_code == 302
    assert Employment.objects.get(profile__user=a2).start_date == good


def test_form_rules(u2_client: Client) -> None:
    html = add(
        u2_client, SECTIONS["employment"], start_date="2016-05", end_date="2016-04", is_present=""
    ).content.decode()
    assert "must not be before the start" in html
    html = add(u2_client, SECTIONS["employment"], position="other", is_present="").content.decode()
    assert "Please describe it" in html and "Enter an end date" in html
    html = add(u2_client, SECTIONS["publication"], authors="").content.decode()
    assert "at least one author" in html
    html = add(u2_client, SECTIONS["publication"], form="book_chapter").content.decode()
    assert "at least one editor" in html
    assert (
        add(
            u2_client, SECTIONS["publication"], form="editorship", authors="", editors="E"
        ).status_code
        == 302
    )


def test_publication_authors_round_trip(u2_client: Client, a2: User) -> None:
    add(u2_client, SECTIONS["publication"], authors="  One \n\nTwo\n")
    pub = Publication.objects.get(profile__user=a2)
    assert pub.authors == ["One", "Two"]
    html = u2_client.get(f"/profile/cv/publication/{pub.pk}/edit/").content.decode()
    assert "One\nTwo" in html
    assert "One, Two" in u2_client.get("/profile/").content.decode()


def test_edit_profile_and_applicant_name(u2_client: Client, a2: User) -> None:
    assert applicant_name(a2) == "a2"  # username fallback: no profile row yet
    assert "Edit profile" in u2_client.get("/profile/edit/").content.decode()
    response = u2_client.post(
        "/profile/edit/",
        {
            "first_name": "Ulla",
            "last_name": "Svensson",
            "orcid": "https://orcid.org/0000-0002-1825-0097",
            "academic_title": "professor",
            "bio": "Ceramics.",
        },
    )
    assert response.status_code == 302
    profile = Profile.objects.get(user=a2)
    assert profile.full_name == "Ulla Svensson" and str(profile) == "Ulla Svensson"
    assert profile.orcid == "0000-0002-1825-0097" and profile.bio == "Ceramics."
    assert applicant_name(a2) == "Ulla Svensson"
    html = u2_client.post(
        "/profile/edit/", {"orcid": "0000-0002-1825-0098", "academic_title": "other"}
    ).content.decode()
    assert "wrong check digit" in html and "Describe the academic title" in html


def test_personal_info_is_private(u2_client: Client, a2: User) -> None:
    html = u2_client.get("/profile/?edit=personal").content.decode()
    assert 'name="save_personal"' in html
    response = u2_client.post(
        "/profile/",
        {"save_personal": "1", "phone": "+46 70 123 45 67", "gender": "woman", "nationality": "SE"},
    )
    assert response.status_code == 302 and response["Location"] == "/profile/#personal"
    profile = Profile.objects.get(user=a2)
    assert profile.phone == "+46 70 123 45 67" and profile.gender == "woman"
    assert "+46 70 123 45 67" in u2_client.get("/profile/").content.decode()
    assert "+46 70 123 45 67" not in u2_client.get("/profile/public/").content.decode()
    bad = u2_client.post("/profile/", {"save_personal": "1", "secondary_email": "nope"})
    assert bad.status_code == 200 and "Enter a valid email address" in bad.content.decode()


def test_documents_form_stays_last_on_the_page(u2_client: Client) -> None:
    """scripts/acceptance.py picks the upload form as the last form on /profile/."""
    for section in SECTIONS.values():
        add(u2_client, section)
    html = u2_client.get("/profile/").content.decode()
    last_form = html.rsplit("<form", 1)[1]
    assert 'name="upload"' in last_form and 'enctype="multipart/form-data"' in last_form
