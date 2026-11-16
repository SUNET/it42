from collections.abc import Callable

import pytest
from django.conf import settings
from django.test import Client

from it42.ro.accounts.models import User


@pytest.mark.parametrize("member", [True, False])
def test_logout_helper_is_available_with_or_without_membership(
    make_member: Callable[..., User], make_user: Callable[..., User], member: bool
) -> None:
    user = (make_member if member else make_user)("logout-user")
    client = Client()
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == (200 if member else 403)
    assert b"it42/logout.js" in response.content
    assert b'data-logout-url="/logout/"' in response.content


def test_logout_rejects_stale_token_but_accepts_current_cookie(
    make_member: Callable[..., User],
) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(make_member("logout-user"))
    client.get("/")
    stale_token = client.cookies[settings.CSRF_COOKIE_NAME].value
    # Model the CSRF rotation caused by a new login in another browser tab.
    current_token = "A" * 32
    client.cookies[settings.CSRF_COOKIE_NAME] = current_token
    assert client.post("/logout/").status_code == 403
    response = client.post("/logout/", {"csrfmiddlewaretoken": stale_token})
    assert response.status_code == 403
    assert "_auth_user_id" in client.session
    response = client.post("/logout/", {"csrfmiddlewaretoken": current_token})
    assert response.status_code == 302
    assert response["Location"] == "/logged-out/"
    assert "_auth_user_id" not in client.session
