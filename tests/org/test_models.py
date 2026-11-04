from django.contrib import admin
from django.test import Client

from it42.org.accounts.models import User


def test_admin_changelists_load(client: Client, db: None) -> None:
    client.force_login(User.objects.create_superuser("root", sso_subject="root"))
    for model in admin.site._registry:
        url = f"/admin/{model._meta.app_label}/{model._meta.model_name}/"
        assert client.get(url).status_code == 200, url


def test_org_has_no_core_models() -> None:
    labels = {m._meta.app_label for m in admin.site._registry}
    assert not {label for label in labels if label.startswith("core_")}
