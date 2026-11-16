from datetime import date, datetime, time

from django.db import models
from django.utils import timezone


def closes_at(deadline: date, deadline_time: time | None) -> datetime:
    """When applications stop being accepted: the deadline day at ``deadline_time`` in the
    site's time zone, or the end of that day when the org gave no time."""
    at = deadline_time if deadline_time is not None else time.max
    return timezone.make_aware(datetime.combine(deadline, at))


class PublicGrant(models.Model):
    """The core's copy of a grant an org has published."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    org_slug = models.SlugField(max_length=16)
    org_name = models.CharField(max_length=100)
    grant_public_id = models.UUIDField()
    title = models.CharField(max_length=200)
    description = models.TextField()
    deadline = models.DateField()
    # Time of day the call closes (orgs publishing before this existed send none).
    deadline_time = models.TimeField(null=True, blank=True)
    form_schema = models.JSONField(default=list)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["org_slug", "grant_public_id"], name="unique_grant_per_org"
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.org_name})"

    def closes_at(self) -> datetime:
        """The moment this call stops accepting applications (see ``closes_at`` above)."""
        return closes_at(self.deadline, self.deadline_time)
