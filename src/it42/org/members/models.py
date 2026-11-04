from django.conf import settings
from django.db import models


class Membership(models.Model):
    """An approved member of this org's staff site. Users without one see the
    not-a-member page. Review panel seats (``org_review.PanelMember``) are separate:
    panel reviewers are not members."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membership"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN
