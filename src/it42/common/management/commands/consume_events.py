import functools
import logging
from typing import Any

import pika
import pika.exceptions
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties

from it42.common.events import RejectEvent
from it42.common.heartbeat import beat
from it42.common.inbox import process
from it42.common.rabbit import connect
from it42.common.routing import inbound_queues

logger = logging.getLogger("it42.consumer")


def on_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    queue: str,
) -> None:
    tag = method.delivery_tag
    if tag is None:  # pika types it optional; every consumed delivery has one
        return
    close_old_connections()
    try:
        process(body, queue)
    except RejectEvent as exc:
        # Forged, malformed or not allowed: dead-letter at once, never retry.
        logger.warning("rejecting message %s from %s: %s", properties.message_id, queue, exc)
        channel.basic_reject(tag, requeue=False)
        return
    except Exception:
        # Possibly transient. The quorum queue's delivery limit dead-letters it
        # after five attempts.
        logger.exception("failed to process message %s from %s", properties.message_id, queue)
        channel.basic_nack(tag, requeue=True)
        return
    channel.basic_ack(tag)


class Command(BaseCommand):
    help = "Consume events from this zone's inbound queues."

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            connection = connect()
            channel = connection.channel()
            channel.basic_qos(prefetch_count=10)
            queues = inbound_queues()
            for queue in queues:
                channel.basic_consume(
                    queue, functools.partial(on_message, queue=queue), auto_ack=False
                )
            logger.info("consuming from %s", ", ".join(queues))
            try:
                while True:
                    connection.process_data_events(time_limit=1)
                    beat("consume")
            except (pika.exceptions.AMQPError, OSError) as exc:
                logger.error("consumer error, reconnecting: %r", exc)
            finally:
                if connection.is_open:
                    connection.close()
