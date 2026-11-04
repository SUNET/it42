import uuid
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.db import models

# Default time the administrating organisation has to sign, after the call closes.
SIGNATURE_DAYS = 7


def default_signature_deadline(deadline: date) -> date:
    return deadline + timedelta(days=SIGNATURE_DAYS)


class Grant(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"

    public_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    deadline = models.DateField()
    # Last day the administrating organisation can sign an application (call deadline +
    # SIGNATURE_DAYS unless the org moves it; it may do so at any time). Filled on save.
    signature_deadline = models.DateField(blank=True)
    form_schema = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.signature_deadline is None and self.deadline is not None:
            self.signature_deadline = default_signature_deadline(self.deadline)
        super().save(*args, **kwargs)
