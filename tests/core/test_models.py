import uuid
from datetime import date

import pytest
from django.contrib import admin
from django.db import IntegrityError
from django.test import Client
from django.utils import timezone

from it42.core.accounts.models import User
from it42.core.applications.models import ApplicationCopy
from it42.core.catalog.models import PublicGrant


def make_grant(org_slug: str = "o1", grant_id: uuid.UUID | None = None) -> PublicGrant:
    return PublicGrant.objects.create(
        org_slug=org_slug,
        org_name="Org 1",
        grant_public_id=grant_id or uuid.uuid4(),
        title="g1",
        description="d",
        deadline=date(2027, 1, 1),
    )


@pytest.mark.django_db
def test_grant_ids_are_unique_per_org() -> None:
    shared = uuid.uuid4()
    make_grant("o1", shared)
    make_grant("o2", shared)  # another org may reuse the id
    with pytest.raises(IntegrityError):
        make_grant("o1", shared)


@pytest.mark.django_db
def test_one_application_per_user_and_grant() -> None:
    user = User.objects.create_user(username="a2", sso_subject="a2")
    grant = make_grant()
    for _ in range(2):
        kwargs = {"public_id": uuid.uuid4(), "user": user, "org_slug": "o1", "grant": grant}
        if ApplicationCopy.objects.exists():
            with pytest.raises(IntegrityError):
                ApplicationCopy.objects.create(**kwargs, submitted_at=timezone.now())
        else:
            ApplicationCopy.objects.create(**kwargs, submitted_at=timezone.now())


@pytest.mark.django_db
def test_admin_changelists_load(client: Client) -> None:
    client.force_login(User.objects.create_superuser("root", sso_subject="root"))
    for model in admin.site._registry:
        url = f"/admin/{model._meta.app_label}/{model._meta.model_name}/"
        assert client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_admin_is_for_superusers_only(client: Client) -> None:
    client.force_login(User.objects.create_user("a2", sso_subject="a2"))
    response = client.get("/admin/")
    assert response.status_code == 302
