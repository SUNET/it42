from collections.abc import Callable
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.test import Client

from it42.org.members.models import Membership


def test_anonymous_is_sent_to_login(client: Client, db: None) -> None:
    response = client.get("/grants/")
    assert response.status_code == 302
    assert response["Location"].startswith("/saml2/login/")


def test_open_paths_need_no_membership(client: Client, db: None) -> None:
    assert client.get("/healthz").status_code == 200


def test_non_member_sees_not_a_member_page(client: Client, make_user: Callable[..., Any]) -> None:
    client.force_login(make_user("a3"))
    for path in ("/", "/members/", "/grants/"):
        response = client.get(path)
        assert response.status_code == 403
        assert b"Not a member of Org 1" in response.content


def test_member_sees_dashboard(client: Client, make_member: Callable[..., Any]) -> None:
    client.force_login(make_member("a1"))
    assert client.get("/").status_code == 200


def test_staff_member_cannot_manage_members(
    client: Client, make_member: Callable[..., Any]
) -> None:
    client.force_login(make_member("a1"))
    assert client.get("/members/").status_code == 403


def test_admin_approves_pending_user(admin_client: Client, make_user: Callable[..., Any]) -> None:
    pending = make_user("a3")
    page = admin_client.get("/members/")
    assert b"a3" in page.content
    admin_client.post(f"/members/approve/{pending.pk}/", {"role": "staff"})
    membership = Membership.objects.get(user=pending)
    assert membership.role == "staff"
    assert membership.approved_by is not None
    assert membership.approved_by.sso_subject == "staff1"


def test_approve_needs_post(admin_client: Client, make_user: Callable[..., Any]) -> None:
    pending = make_user("a3")
    assert admin_client.get(f"/members/approve/{pending.pk}/").status_code == 405


def test_last_admin_cannot_be_removed_or_demoted(admin_client: Client) -> None:
    only = Membership.objects.get()
    admin_client.post(f"/members/{only.pk}/remove/")
    admin_client.post(f"/members/{only.pk}/role/", {"role": "staff"})
    only.refresh_from_db()
    assert only.role == "admin"


def test_admin_removes_member(admin_client: Client, make_member: Callable[..., Any]) -> None:
    member = make_member("a1")
    admin_client.post(f"/members/{member.membership.pk}/remove/")
    assert not Membership.objects.filter(user=member).exists()


def test_bootstrap_org_admin(make_user: Callable[..., Any]) -> None:
    user = make_user("staff1")
    call_command("bootstrap_org_admin", "--subject", "staff1")
    assert Membership.objects.get(user=user).role == "admin"


def test_bootstrap_org_admin_requires_existing_user(db: None) -> None:
    with pytest.raises(CommandError, match="must log in"):
        call_command("bootstrap_org_admin", "--subject", "nobody")


def test_logged_out_page_is_public(client: Client, db: None) -> None:
    response = client.get("/logged-out/")
    assert response.status_code == 200
    assert b"You have been logged out" in response.content
    # The staff site's design, with a way back to the public site.
    assert b"it-granter" in response.content and b'href="https://it42.vr/"' in response.content


def test_listed_subject_becomes_admin_on_login(
    client: Client, make_user: Callable[..., Any], settings: Any
) -> None:
    settings.ORG_BOOTSTRAP_ADMINS = ["staff1"]
    user = make_user("staff1")
    assert not Membership.objects.filter(user=user).exists()
    client.force_login(user)  # sends user_logged_in like the SAML login does
    membership = Membership.objects.get(user=user)
    assert membership.role == Membership.Role.ADMIN and membership.approved_by is None
    assert client.get("/members/").status_code == 200
    client.force_login(user)  # idempotent
    assert Membership.objects.filter(user=user).count() == 1


def test_listed_subject_is_made_admin_again_if_demoted(
    client: Client, make_member: Callable[..., Any], settings: Any
) -> None:
    settings.ORG_BOOTSTRAP_ADMINS = ["staff1"]
    user = make_member("staff1", Membership.Role.STAFF)
    client.force_login(user)
    assert Membership.objects.get(user=user).role == Membership.Role.ADMIN


def test_unlisted_subject_gets_no_membership(
    client: Client, make_user: Callable[..., Any], settings: Any
) -> None:
    settings.ORG_BOOTSTRAP_ADMINS = ["staff1"]
    user = make_user("staff2")
    client.force_login(user)
    assert not Membership.objects.filter(user=user).exists()
    assert client.get("/").status_code == 403


def test_bootstrap_admins_setting_is_parsed_from_env(monkeypatch: Any) -> None:
    import importlib

    monkeypatch.setenv("ORG_BOOTSTRAP_ADMINS", " staff1, staff9 ,")
    from it42.settings import org as org_settings

    module = importlib.reload(org_settings)
    assert module.ORG_BOOTSTRAP_ADMINS == ["staff1", "staff9"]
    monkeypatch.delenv("ORG_BOOTSTRAP_ADMINS")
    importlib.reload(org_settings)
