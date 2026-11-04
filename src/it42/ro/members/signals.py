"""Bind memberships to accounts at login, by the email the IdP sends.

djangosaml2 refreshes ``user.email`` on every login. At that moment:

- the directory decides who is admin: the organisation whose ``admin_email`` this is gets
  this person as its one admin (a previous admin of it becomes a signer), and a person who
  is an admin but no longer listed becomes a signer;
- a membership added for this email by an admin (a signer) is bound to the account.
"""

import logging
from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.db import transaction

from it42.common import research_orgs

from .models import Membership

logger = logging.getLogger(__name__)


def sync_membership(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return
    org = research_orgs.administered_by(email)
    with transaction.atomic():
        # Another email bound to this account earlier (the IdP email changed) lets go.
        Membership.objects.filter(user=user).exclude(email=email).update(user=None)
        if org is not None:
            Membership.objects.filter(research_org=org.slug, role=Membership.Role.ADMIN).exclude(
                email=email
            ).update(role=Membership.Role.SIGNER)
            membership, _ = Membership.objects.update_or_create(
                email=email,
                defaults={"research_org": org.slug, "role": Membership.Role.ADMIN, "user": user},
            )
            logger.info("%s is the admin of %s", email, org.name)
            return
        membership = Membership.objects.filter(email=email).first()
        if membership is None:
            return
        membership.user = user
        if membership.is_admin:
            # No longer the directory's admin for this organisation.
            membership.role = Membership.Role.SIGNER
        membership.save(update_fields=["user", "role"])


def connect() -> None:
    user_logged_in.connect(sync_membership, dispatch_uid="ro_members.sync_membership")
