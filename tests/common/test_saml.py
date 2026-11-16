from typing import Any

import pytest
from django.test import RequestFactory

from it42.common.saml import SubjectSaml2Backend
from it42.common.saml_config import SAML_ATTRIBUTE_MAPPING
from it42.core.accounts.models import User

ATTRS = {
    "uid": ["a2"],
    "email": ["oskar.bergstrom@kth.se"],
    "givenName": ["Oskar"],
    "sn": ["Bergström"],
}


def session_info(**overrides: Any) -> dict[str, Any]:
    return {"ava": {**ATTRS, **overrides}, "issuer": "https://idp.it42.vr/idp/metadata"}


def authenticate(info: dict[str, Any], assertion_id: str = "a1") -> Any:
    return SubjectSaml2Backend().authenticate(
        RequestFactory().post("/saml2/acs/"),
        session_info=info,
        attribute_mapping=SAML_ATTRIBUTE_MAPPING,
        assertion_info={"assertion_id": assertion_id, "not_on_or_after": None},
    )


@pytest.mark.django_db
def test_creates_user_keyed_on_subject() -> None:
    user = authenticate(session_info())
    assert user.sso_subject == "a2"
    assert user.username == "a2"
    assert user.email == "oskar.bergstrom@kth.se"
    assert user.get_full_name() == "Oskar Bergström"


@pytest.mark.django_db
def test_changed_email_keeps_the_same_user() -> None:
    first = authenticate(session_info(), "a1")
    second = authenticate(session_info(email=["new@kth.se"]), "a2")
    assert first.pk == second.pk
    assert User.objects.get().email == "new@kth.se"


@pytest.mark.django_db
def test_same_email_different_subject_is_a_different_user() -> None:
    first = authenticate(session_info(), "a1")
    second = authenticate(session_info(uid=["u9"]), "a2")
    assert first.pk != second.pk


@pytest.mark.django_db
def test_missing_uid_is_rejected() -> None:
    info = session_info()
    del info["ava"]["uid"]
    assert authenticate(info) is None


@pytest.mark.django_db
def test_replayed_assertion_is_rejected() -> None:
    assert authenticate(session_info(), "same") is not None
    assert authenticate(session_info(), "same") is None
