"""The redesigned profile page: tabs, facts, CV table, dialogs."""

from datetime import date

from django.test import Client

from it42.core.accounts.models import User
from it42.core.profiles.models import (
    AssociateProfessorship,
    Award,
    Employment,
    IntellectualProperty,
    Profile,
    Publication,
    ResearchEducation,
    ResearchExchange,
    ResearchInterruption,
    Supervision,
)
from it42.core.profiles.stats import duration, key_facts, load_cv, months_of


def make_cv(profile: Profile) -> None:
    Employment.objects.create(
        profile=profile, employer="Uppsala University", department="Physics",
        position="professor", start_date="2021-03", is_present=True,
    )  # fmt: skip
    ResearchEducation.objects.create(
        profile=profile, university="KTH", kind="phd", subject="Physics", degree_date="2015-01"
    )
    ResearchInterruption.objects.create(
        profile=profile, start_date="2018-01", end_date="2019-01", description="Parental leave"
    )
    AssociateProfessorship.objects.create(
        profile=profile, university="KTH", subject="Docent in Physics", year=2020
    )
    for title, form in [("Ionian kilns", "journal_article"), ("Glazes", "conference")]:
        Publication.objects.create(profile=profile, title=title, form=form, publication_date="2022")
    Supervision.objects.create(profile=profile, supervised_type="phd", first_name="A")
    Supervision.objects.create(
        profile=profile, kind="group", supervised_type="master", number_of_people=6
    )
    ResearchExchange.objects.create(profile=profile, host="CERN", months=9)
    Award.objects.create(profile=profile, award="Best paper", year=2023)
    IntellectualProperty.objects.create(profile=profile, title="Kiln", date_approved="2021")
    IntellectualProperty.objects.create(profile=profile, title="Glaze")


def test_months_and_duration() -> None:
    assert months_of("2015-01", "2024-03") == 110
    assert months_of("2015", "2016") == 12 and months_of("", "2016") == 0
    assert duration(110) == "9 y 2 m" and duration(12) == "1 y" and duration(1) == "1 month"


def test_key_facts_from_the_cv(a2: User) -> None:
    profile = Profile.objects.create(user=a2)
    assert key_facts(load_cv(profile)) == []  # no data, no tiles
    make_cv(profile)
    facts = {f.label: f.value for f in key_facts(load_cv(profile), today=date(2026, 3, 1))}
    assert facts == {
        "Docent in Docent in Physics": "2020",
        "Since PhD, after leave": "10 y 2 m",  # 11 y 2 m minus 12 months of leave
        "Publications · 2 peer reviewed": "2",
        "PhD and Master's students": "1 + 6",
        "Research exchanges": "9 months",
        "Awards and distinctions": "1",
        "Patents granted and pending": "1 + 1",
    }


def test_leave_counts_by_overlap_with_the_time_since_phd(a2: User) -> None:
    profile = Profile.objects.create(user=a2)
    ResearchEducation.objects.create(
        profile=profile, university="KTH", kind="phd", degree_date="2015-06"
    )
    # Year-only start in the PhD year, and leave that began before the degree: only the
    # months after June 2015 count (2015-06..2015-12 = 6, plus 2016-01..2016-12 = 12).
    ResearchInterruption.objects.create(profile=profile, start_date="2015", end_date="2015")
    ResearchInterruption.objects.create(profile=profile, start_date="2014-01", end_date="2016")
    (fact,) = key_facts(load_cv(profile), today=date(2026, 6, 1))
    assert fact.label == "Since PhD, after leave"
    assert fact.value == duration(11 * 12 - 6 - 18)  # 132 months minus both overlaps


def test_tabs_and_profile_column(u2_client: Client, a2: User) -> None:
    profile = Profile.objects.create(user=a2, first_name="Ulla", bio="Kilns.")
    make_cv(profile)
    html = u2_client.get("/profile/").content.decode()
    for tab in ("#overview", "#academic-cv", "#stats", "#cv-upload", "#personal"):
        assert f'href="{tab}" role="tab"' in html
    assert "Uppsala University" in html and "Physics" in html  # current employment
    assert "1 + 6" in html and "Conference contributions" not in html
    assert "1</strong><span>Conference contribution<" in html  # Stats tile
    assert "Citations" not in html and "h-index" not in html and "AI" not in html
    assert 'href="/profile/edit/"' in html and 'href="/profile/data/"' in html


def test_cv_table_filters_without_javascript(u2_client: Client, a2: User) -> None:
    make_cv(Profile.objects.create(user=a2))

    def visible(query: str) -> list[str]:
        html = u2_client.get(f"/profile/?{query}").content.decode()
        rows = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("<tr ")[1:]
        return [
            r.split('data-section="', 1)[1].split('"', 1)[0] for r in rows if " hidden>" not in r
        ]

    everything = visible("")
    assert len(everything) == 12 and everything[0] == "award"  # newest first: 2023
    assert visible("section=publication") == ["publication", "publication"]
    assert visible("q=kiln") == ["publication", "ip"]
    assert visible("sort=oldest")[0] == "research_education"
    assert len(visible("section=bogus")) == 12  # an unknown section means All
    html = u2_client.get("/profile/?q=kiln").content.decode()
    assert "2 results for “kiln”" in html


def test_banner_steps_and_orcid_button(u2_client: Client, a2: User) -> None:
    html = u2_client.get("/profile/").content.decode()
    assert "Finish your profile" in html and "1 of 5 steps" in html  # name: the username
    assert 'href="/profile/orcid/"' in html and "Import from ORCID" in html
    Profile.objects.filter(user=a2).update(first_name="U", bio="B", orcid="0000-0002-1825-0097")
    html = u2_client.get("/profile/").content.decode()
    assert "3 of 5 steps" in html
    assert 'name="orcid" value="0000-0002-1825-0097"' in html  # one click starts an import


def test_edit_data_research_areas(u2_client: Client, a2: User) -> None:
    html = u2_client.get("/profile/data/").content.decode()
    assert "Edit your profile data" in html and "Add publication" in html
    response = u2_client.post("/profile/data/", {"areas": "Kilns, glazes\nkilns\n Ceramics "})
    assert response.status_code == 302
    assert Profile.objects.get(user=a2).research_areas == ["Kilns", "glazes", "Ceramics"]
    assert "glazes" in u2_client.get("/profile/").content.decode()


def test_public_preview_is_read_only(u2_client: Client, a2: User) -> None:
    profile = Profile.objects.create(user=a2, first_name="Ulla", address="Secret street 1")
    make_cv(profile)
    html = u2_client.get("/profile/public/").content.decode()
    assert "Public profile" in html and "preview" in html
    assert "Ionian kilns" in html and "Secret street" not in html
    assert "/profile/cv/" not in html and 'href="#personal"' not in html
    assert 'method="post"' not in html.split("</aside>", 2)[1]  # nothing to change here
