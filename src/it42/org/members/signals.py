"""Automatic admins: subjects listed in ``ORG_BOOTSTRAP_ADMINS`` become admins on login.

Each org's env file lists its first admin (staff1 for o1, staff2 for o2) so a fresh stack
needs no manual ``bootstrap_org_admin`` step. The listing is re-applied on every login,
so a listed subject that was demoted or removed on the Members page is an admin again
the next time they log in.
"""

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.utils import timezone

from .models import Membership

logger = logging.getLogger(__name__)


def bootstrap_admin(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    subject = getattr(user, "sso_subject", "")
    if not subject or subject not in settings.ORG_BOOTSTRAP_ADMINS:
        return
    membership, created = Membership.objects.get_or_create(
        user=user, defaults={"role": Membership.Role.ADMIN, "approved_at": timezone.now()}
    )
    if not created and membership.role != Membership.Role.ADMIN:
        membership.role = Membership.Role.ADMIN
        membership.save(update_fields=["role"])
        created = True
    if created:
        logger.info("Bootstrap admin %s granted admin membership in %s", subject, settings.ORG_NAME)


def connect() -> None:
    user_logged_in.connect(bootstrap_admin, dispatch_uid="org_members.bootstrap_admin")
