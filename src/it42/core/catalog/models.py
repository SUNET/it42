from django.db import models


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
