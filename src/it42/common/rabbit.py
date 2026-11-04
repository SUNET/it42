"""RabbitMQ connection helper for the worker commands."""

import logging
import time

import pika
import pika.exceptions
from django.conf import settings

logger = logging.getLogger(__name__)


def connection_parameters() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        virtual_host=settings.RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD),
        heartbeat=30,
        blocked_connection_timeout=60,
        client_properties={"connection_name": f"it42-{settings.APP_ROLE}-{settings.ORG_SLUG}"},
    )


def connect(retry_seconds: float = 3.0) -> pika.BlockingConnection:
    """Connect, retrying until the broker accepts us."""
    if not settings.RABBITMQ_USER:
        raise RuntimeError("RABBITMQ_USER is not set; only workers get broker credentials")
    while True:
        try:
            return pika.BlockingConnection(connection_parameters())
        except pika.exceptions.AMQPConnectionError as exc:
            logger.warning("RabbitMQ not reachable (%s); retrying", exc)
            time.sleep(retry_seconds)
