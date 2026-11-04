from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A local account, linked to the IdP by its stable SAML subject."""

    sso_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)

    def __str__(self) -> str:
        return self.get_full_name() or self.username
