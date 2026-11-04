"""Who acts for a research organisation (milestone 14)."""

from collections.abc import Callable

import pytest
from django.contrib.auth.signals import user_logged_in
from django.test import Client, RequestFactory

from it42.ro.accounts.models import User
from it42.ro.members.models import Membership

from .conftest import KTH_ADMIN, UU_ADMIN, client_for


def login(user: User) -> None:
    user_logged_in.send(sender=User, request=RequestFactory().get("/"), user=user)


def test_anonymous_users_are_sent_to_login(client: Client, db: None) -> None:
    response = client.get("/")
    assert response.status_code == 302 and response["Location"].startswith("/saml2/login/")


def test_users_without_a_membership_see_no_data(make_user: Callable[..., User]) -> None:
    response = client_for(make_user("a1")).get("/")
    assert response.status_code == 403
    assert "You do not act for a research organisation" in response.content.decode()


def test_directory_admin_becomes_admin_at_login(make_user: Callable[..., User]) -> None:
    user = make_user("ro2", email=KTH_ADMIN.upper())
    login(user)
    membership = Membership.objects.get(user=user)
    assert (membership.research_org, membership.role) == ("kth", "admin")
    assert client_for(user).get("/people/").status_code == 200


def test_a_new_directory_admin_replaces_the_old_one(
    make_member: Callable[..., User], make_user: Callable[..., User]
) -> None:
    old = make_member("old", "kth", Membership.Role.ADMIN, "old.admin@kth.se")
    login(make_user("ro2", email=KTH_ADMIN))
    assert Membership.objects.get(user=old).role == "signer"
    # And a listed admin who logs in again, no longer in the directory, is a signer.
    login(old)
    assert Membership.objects.get(user=old).role == "signer"


def test_signer_seat_is_bound_at_login(kth_admin: Client, make_user: Callable[..., User]) -> None:
    kth_admin.post("/people/add/", {"email": "Sig2@KTH.se"})
    membership = Membership.objects.get(email="sig2@kth.se")
    assert membership.user is None and membership.research_org == "kth"
    user = make_user("sig2", email="sig2@kth.se")
    login(user)
    membership.refresh_from_db()
    assert membership.user == user
    assert client_for(user).get("/").status_code == 200
    # Signers do not manage people.
    assert client_for(user).get("/people/").status_code == 403


def test_signer_who_logged_in_before_is_bound_at_once(
    kth_admin: Client, make_user: Callable[..., User]
) -> None:
    user = make_user("sig3", email="sig3@kth.se")
    kth_admin.post("/people/add/", {"email": "sig3@kth.se"})
    assert Membership.objects.get(email="sig3@kth.se").user == user


@pytest.mark.parametrize("email", ["jonas.ek@uu.se", UU_ADMIN, "not-an-email"])
def test_admin_cannot_add_someone_of_another_organisation(
    kth_admin: Client, uu_signer: Client, email: str
) -> None:
    before = Membership.objects.count()
    kth_admin.post("/people/add/", {"email": email})
    assert Membership.objects.count() == before
    assert Membership.objects.get(email="jonas.ek@uu.se").research_org == "uu"


def test_admin_removes_signers_of_their_own_organisation_only(
    kth_admin: Client, make_member: Callable[..., User]
) -> None:
    make_member("sig1", "uu", email="jonas.ek@uu.se")
    make_member("sig2", "kth", email="sig2@kth.se")
    uu = Membership.objects.get(email="jonas.ek@uu.se")
    kth = Membership.objects.get(email="sig2@kth.se")
    admin = Membership.objects.get(role="admin")
    assert kth_admin.post(f"/people/{uu.pk}/remove/").status_code == 404
    assert kth_admin.post(f"/people/{admin.pk}/remove/").status_code == 404
    kth_admin.post(f"/people/{kth.pk}/remove/")
    assert not Membership.objects.filter(pk=kth.pk).exists()


def test_people_page_lists_the_organisation(kth_admin: Client, uu_signer: Client) -> None:
    body = kth_admin.get("/people/").content.decode()
    assert KTH_ADMIN in body and "jonas.ek@uu.se" not in body
