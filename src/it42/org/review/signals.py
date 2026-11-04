"""Bind panel seats to users by email when they log in.

Seats are created by the FO with an email address only. djangosaml2 refreshes
``user.email`` from the IdP on every login, so at that moment every unbound seat with the
same address (case-insensitive) is bound to the account. ``services.add_seat`` covers the
other order (a seat added after the person has already logged in once).
"""

import logging
from typing import Any

from django.contrib.auth.signals import user_logged_in

from .models import PanelMember

logger = logging.getLogger(__name__)


def bind_seats(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return
    bound = PanelMember.objects.filter(email=email, user__isnull=True).update(user=user)
    if bound:
        logger.info("Bound %d panel seat(s) to %s", bound, getattr(user, "sso_subject", user))


def connect() -> None:
    user_logged_in.connect(bind_seats, dispatch_uid="org_review.bind_seats")
