import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone

from it42.common.pdf import check_pdf_bytes
from it42.core.accounts.models import User
from it42.core.catalog.models import PublicGrant
from it42.core.profiles.models import Document

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
SCHEMA = [
    {"name": "project_title", "label": "Project title", "type": "text", "required": True},
    {"name": "budget", "label": "Budget", "type": "number", "required": True},
]


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    def make(subject: str) -> User:
        return User.objects.create_user(
            username=subject, sso_subject=subject, email=f"{subject}@kth.se", first_name=subject
        )

    return make


@pytest.fixture
def a2(make_user: Callable[..., User]) -> User:
    return make_user("a2")


@pytest.fixture
def u2_client(a2: User) -> Client:
    client = Client()
    client.force_login(a2)
    return client


@pytest.fixture
def make_grant(db: None) -> Callable[..., PublicGrant]:
    def make(org: str = "o1", **extra: Any) -> PublicGrant:
        fields: dict[str, Any] = {
            "org_slug": org,
            "org_name": {"o1": "Org 1", "o2": "Org 2"}[org],
            "grant_public_id": uuid.uuid4(),
            "title": f"grant of {org}",
            "description": "d",
            "deadline": timezone.localdate() + timedelta(days=30),
            "form_schema": SCHEMA,
        }
        fields.update(extra)
        return PublicGrant.objects.create(**fields)

    return make


@pytest.fixture
def make_document() -> Callable[..., Document]:
    def make(user: User, name: str = "cv.pdf", content: bytes = PDF) -> Document:
        doc = Document(
            user=user, original_name=name, sha256=check_pdf_bytes(content), size=len(content)
        )
        doc.file.save(name, ContentFile(content), save=True)
        return doc

    return make
