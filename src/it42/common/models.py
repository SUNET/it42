"""Transactional outbox and inbox, installed in every zone's database."""

import uuid

from django.db import models


class OutboxEvent(models.Model):
    """An event waiting to be published. Written in the same transaction as the
    state change it describes; ``relay_outbox`` publishes it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exchange = models.CharField(max_length=64)
    type = models.CharField(max_length=64)
    version = models.PositiveSmallIntegerField(default=1)
    occurred_at = models.DateTimeField()
    application_id = models.UUIDField(null=True, blank=True)
    grant_id = models.UUIDField(null=True, blank=True)
    seq = models.PositiveIntegerField(null=True, blank=True)
    payload = models.JSONField()
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["occurred_at"]
        indexes = [
            models.Index(
                fields=["occurred_at"],
                name="outbox_unpublished",
                condition=models.Q(published_at__isnull=True),
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} -> {self.exchange} ({self.id})"


class ProcessedEvent(models.Model):
    """Inbox: one row per consumed event id, so redeliveries are skipped."""

    event_id = models.UUIDField(primary_key=True)
    type = models.CharField(max_length=64)
    queue = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.type} from {self.queue} ({self.event_id})"
