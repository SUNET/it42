from django.conf import settings
from django.db import models


class Membership(models.Model):
    """A person who acts for one research organisation on this site.

    Keyed by email, like review panel seats: the admin comes from the directory's
    ``admin_email``, signers are added by that admin, and both are bound to an account
    when they log in with that email (``signals.py``). One membership per email, so a
    person acts for one organisation only.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        SIGNER = "signer", "Signer"

    email = models.EmailField(unique=True)
    # research_orgs slug (config/research_orgs.toml)
    research_org = models.SlugField(max_length=32)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.SIGNER)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ro_membership",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    added_at = models.DateTimeField(auto_now_add=True)
    user_id: int | None

    class Meta:
        ordering = ["research_org", "role", "email"]

    def __str__(self) -> str:
        return f"{self.email} ({self.research_org}, {self.role})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN
