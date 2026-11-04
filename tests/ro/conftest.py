import base64
import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from it42.common.events import Envelope
from it42.common.formschema import BASE_FIELDS
from it42.common.inbox import process
from it42.ro.accounts.models import User
from it42.ro.members.models import Membership
from it42.ro.signing.models import SignatureRequest

PDF = b"%PDF-1.4\n%%EOF\n"
SCHEMA = [
    *BASE_FIELDS,
    {"name": "project_title", "label": "Project title", "type": "text", "required": True},
]
# admin_email of KTH and Uppsala University in config/research_orgs.toml.example
KTH_ADMIN = "nils.hedlund@kth.se"
UU_ADMIN = "lena.wikstrom@uu.se"


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    def make(subject: str, email: str = "", **extra: Any) -> User:
        return User.objects.create_user(
            username=subject, sso_subject=subject, email=email or f"{subject}@example.org", **extra
        )

    return make


@pytest.fixture
def make_member(make_user: Callable[..., User]) -> Callable[..., User]:
    def make(
        subject: str, org: str = "kth", role: str = Membership.Role.SIGNER, email: str = ""
    ) -> User:
        user = make_user(subject, email=email)
        Membership.objects.create(email=user.email, research_org=org, role=role, user=user)
        return user

    return make


def client_for(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def kth_admin(make_member: Callable[..., User]) -> Client:
    return client_for(make_member("ro2", "kth", Membership.Role.ADMIN, KTH_ADMIN))


@pytest.fixture
def kth_signer(make_member: Callable[..., User]) -> Client:
    return client_for(make_member("sig2", "kth", email="sig2@kth.se"))


@pytest.fixture
def uu_signer(make_member: Callable[..., User]) -> Client:
    return client_for(make_member("sig1", "uu", email="jonas.ek@uu.se"))


def requested(
    org: str = "kth", sender: str = "o1", app_id: uuid.UUID | None = None, **payload: Any
) -> SignatureRequest:
    app_id = app_id or uuid.uuid4()
    body: dict[str, Any] = {
        "application_id": str(app_id),
        "grant_public_id": str(uuid.uuid4()),
        "grant_title": "Solar research",
        "research_org": org,
        "applicant": {"subject": "a2", "name": "Oskar Bergström", "email": "o@kth.se"},
        "answers": {
            "applicant_name": "Oskar Bergström",
            "applicant_email": "o@kth.se",
            "administrating_organisation": org,
            "project_title": "Solar",
        },
        "form_schema": SCHEMA,
        "submitted_at": timezone.now().isoformat(),
        "deadline": (timezone.localdate() + timedelta(days=7)).isoformat(),
        "documents": [
            {
                "name": "cv.pdf",
                "sha256": hashlib.sha256(PDF).hexdigest(),
                "content": base64.b64encode(PDF).decode(),
            }
        ],
    }
    body.update(payload)
    envelope = Envelope(
        type="signature.requested",
        payload=body,
        application_id=app_id,
        grant_id=uuid.UUID(body["grant_public_id"]),
    )
    process(envelope.to_json(), f"{sender}-to-ro")
    return SignatureRequest.objects.get(public_id=app_id)


@pytest.fixture
def kth_request(db: None) -> SignatureRequest:
    return requested("kth")
