from django.conf import settings


def test_org_installs_only_org_apps() -> None:
    assert not [a for a in settings.INSTALLED_APPS if a.startswith("it42.core")]
    assert settings.AUTH_USER_MODEL == "org_accounts.User"
