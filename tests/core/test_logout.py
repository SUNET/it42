from django.test import Client

from it42.common.saml_config import BINDING_HTTP_POST, build_saml_config
from it42.core.accounts.models import User


def test_logout_needs_post(u2_client: Client) -> None:
    assert u2_client.get("/logout/").status_code == 405
    # djangosaml2's GET logout route is replaced too.
    assert u2_client.get("/saml2/logout/").status_code == 405


def test_logout_without_saml_session_is_local(u2_client: Client, a2: User) -> None:
    response = u2_client.post("/logout/")
    assert response.status_code == 302
    assert response["Location"] == "/logged-out/"
    assert "_auth_user_id" not in u2_client.session


def test_logged_out_lands_on_the_home_page_with_a_notice(client: Client, db: None) -> None:
    response = client.get("/logged-out/", follow=True)
    assert response.redirect_chain == [("/", 302)]
    assert b"You have been logged out" in response.content


def test_logout_requires_csrf_token(a2: User) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(a2)
    assert client.post("/logout/").status_code == 403


def test_sp_config_supports_single_logout() -> None:
    sp = build_saml_config(site_url="https://it42.vr", key_dir="k", idp_metadata="m.xml", name="x")[
        "service"
    ]["sp"]
    assert sp["endpoints"]["single_logout_service"] == [
        ("https://it42.vr/saml2/ls/post/", BINDING_HTTP_POST)
    ]
    assert sp["logout_requests_signed"] is True
    assert sp["want_logout_response_signed"] is True
