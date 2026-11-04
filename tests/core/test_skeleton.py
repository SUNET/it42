from django.conf import settings
from django.test import Client


def test_core_installs_only_core_apps() -> None:
    assert not [a for a in settings.INSTALLED_APPS if a.startswith("it42.org")]
    assert settings.AUTH_USER_MODEL == "core_accounts.User"


def test_home_is_themed(client: Client, db: None) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "--bs-primary: #020344" in body
    assert "IT42 Grants" in body


def test_healthz(client: Client) -> None:
    assert client.get("/healthz").content == b"ok"
