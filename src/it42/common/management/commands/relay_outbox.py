import logging
from typing import Any, Protocol

import pika
import pika.exceptions
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

from it42.common.heartbeat import beat
from it42.common.models import OutboxEvent
from it42.common.outbox import envelope_of
from it42.common.rabbit import connect

logger = logging.getLogger("it42.relay")


class Publisher(Protocol):
    """The part of pika's BlockingChannel the relay uses."""

    def basic_publish(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        properties: pika.BasicProperties | None = None,
        mandatory: bool = False,
    ) -> None: ...


def publish(channel: Publisher, event: OutboxEvent) -> None:
    """Publish persistently with confirms. Raises if the broker refuses or can't route it."""
    channel.basic_publish(
        exchange=event.exchange,
        routing_key=event.exchange,
        body=envelope_of(event).to_json(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=str(event.id),
            type=event.type,
        ),
        mandatory=True,
    )


def relay_batch(channel: Publisher, batch_size: int = 100) -> int:
    """Publish pending events in order; return how many were published.

    Rows are locked with SKIP LOCKED so several relays never publish the same row.
    A failure records the error and stops the batch so ordering is preserved.
    """
    failure: Exception | None = None
    published = 0
    with transaction.atomic():
        pending = (
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(published_at__isnull=True)
            .order_by("occurred_at")[:batch_size]
        )
        for event in pending:
            try:
                publish(channel, event)
            except Exception as exc:
                event.attempts += 1
                event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                event.save(update_fields=["attempts", "last_error"])
                failure = exc
                break
            event.published_at = timezone.now()
            event.attempts += 1
            event.save(update_fields=["published_at", "attempts"])
            published += 1
    if failure is not None:
        raise failure
    return published


class Command(BaseCommand):
    help = "Publish outbox events to RabbitMQ, once a second."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true", help="Publish one batch and exit")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            connection = connect()
            channel = connection.channel()
            channel.confirm_delivery()
            logger.info("relay connected")
            try:
                while True:
                    count = relay_batch(channel)
                    if count:
                        logger.info("published %d event(s)", count)
                    beat("relay")
                    if options["once"]:
                        return
                    if not count:
                        connection.sleep(1.0)  # also services heartbeats
            except (pika.exceptions.AMQPError, OSError) as exc:
                logger.error("relay error, reconnecting: %r", exc)
                if options["once"]:
                    raise
            finally:
                if connection.is_open:
                    connection.close()
