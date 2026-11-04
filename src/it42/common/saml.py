"""SAML backend shared by every site."""

import logging
from datetime import datetime
from typing import Any

from django.core.cache import cache
from django.utils import timezone
from djangosaml2.backends import Saml2Backend

logger = logging.getLogger(__name__)


class SubjectSaml2Backend(Saml2Backend):
    """Key users on ``sso_subject`` and never on email.

    djangosaml2 creates unknown users with only the lookup field set. The username
    must be unique too, so it mirrors the subject.
    """

    def get_or_create_user(
        self,
        user_lookup_key: str,
        user_lookup_value: Any,
        create_unknown_user: bool,
        idp_entityid: str,
        attributes: dict,
        attribute_mapping: dict,
        request: Any,
    ) -> tuple[Any, bool]:
        user, created = super().get_or_create_user(
            user_lookup_key,
            user_lookup_value,
            create_unknown_user,
            idp_entityid=idp_entityid,
            attributes=attributes,
            attribute_mapping=attribute_mapping,
            request=request,
        )
        if created and user is not None:
            user.username = user_lookup_value
        return user, created

    def is_authorized(
        self,
        attributes: dict,
        attribute_mapping: dict,
        idp_entityid: str,
        assertion_info: dict,
        **kwargs: Any,
    ) -> bool:
        """Reject replayed assertions (SAML core 4.1.4.5)."""
        if not assertion_info:
            return True
        assertion_id = assertion_info.get("assertion_id")
        if not assertion_id:
            return True
        timeout = 300
        not_on_or_after = assertion_info.get("not_on_or_after")
        if isinstance(not_on_or_after, str):
            try:
                expiry = datetime.fromisoformat(not_on_or_after.replace("Z", "+00:00"))
                timeout = max(1, int((expiry - timezone.now()).total_seconds()) + 60)
            except ValueError:
                pass
        if not cache.add(f"saml-assertion:{assertion_id}", True, timeout=timeout):
            logger.warning("Replayed SAML assertion %s rejected", assertion_id)
            return False
        return True
