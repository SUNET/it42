"""The 23 Oct 2026 design update on the core site: the text pages,
the navigation that points at them, the applicant's Activity tab and the submit dialog."""

from collections.abc import Callable

import pytest
from django.test import Client

from it42.core.applications.models import ApplicationCopy, QuestionCopy
from it42.core.catalog.models import PublicGrant
from it42.core.profiles.models import Document

from .test_applying import ANSWERS, apply


@pytest.mark.parametrize(
    ("slug", "title"),
    [
        ("about", "About IT42"),
        ("how-it-works", "How it works"),
        ("help", "Help"),
        ("contact", "Contact us"),
        ("accessibility", "Accessibility statement"),
        ("privacy", "Privacy policy"),
        ("cookies", "Cookie policy"),
    ],
)
def test_text_pages(client: Client, slug: str, title: str) -> None:
    body = client.get(f"/pages/{slug}/").content.decode()
    assert f"<h1>{title}</h1>" in body
    assert "min read" in body and "On this page" in body
    assert 'src="/static/it42/site.js"' in body


def test_notice_banner_and_footer_links(client: Client, db: None) -> None:
    body = client.get("/pages/contact/").content.decode()
    assert 'class="it-notice"' in body and "placeholders" in body
    assert 'class="it-notice"' not in client.get("/pages/cookies/").content.decode()
    home = client.get("/").content.decode()
    for slug in ("about", "how-it-works", "help", "accessibility", "contact"):
        assert f'href="/pages/{slug}/"' in home
    assert "data-reveal" in home and "it-glow-applicant" in home
    assert "Subscribe" not in home  # the design's newsletter box has no feature behind it


def test_applicant_activity_and_next_step(
    u2_client: Client,
    make_grant: Callable[..., PublicGrant],
) -> None:
    grant = make_grant("o1")
    apply(u2_client, grant, **ANSWERS)
    application = ApplicationCopy.objects.get()
    QuestionCopy.objects.create(
        application=application,
        question_public_id="00000000-0000-0000-0000-000000000001",
        text="QUESTION-MARKER",
        asked_at=application.submitted_at,
    )
    body = u2_client.get(f"/my/applications/{application.public_id}/").content.decode()
    assert "You submitted the application" in body
    assert "QUESTION-MARKER" in body and "Grant details" in body
    assert "The funder confirms it has received your application." in body


def test_apply_page_has_the_submit_dialog(
    u2_client: Client,
    make_grant: Callable[..., PublicGrant],
    make_document: Callable[..., Document],
) -> None:
    grant = make_grant("o1")
    body = u2_client.get(
        f"/grants/{grant.org_slug}/{grant.grant_public_id}/apply/"
    ).content.decode()
    assert '<dialog class="it-modal" id="submit-dialog"' in body
    assert 'id="confirm" name="confirm"' in body  # still works without JavaScript
    assert 'id="confirm-dialog">' in body and 'name="confirm"' not in body.split("<dialog", 1)[1]
