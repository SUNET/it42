"""Run inside the RO worker: probe RabbitMQ permissions with the RO zone's credentials.

The RO zone may only publish to ro-to-<org> and read <org>-to-ro; it has no link to the
core. Each probe opens a fresh channel and prints "<name> ALLOWED" or
"<name> <code> <text>". Publishes use publisher confirms so a refusal is synchronous.
"""

import os
import sys

import pika
import pika.exceptions

params = pika.ConnectionParameters(
    host=os.environ["RABBITMQ_HOST"],
    virtual_host=os.environ["RABBITMQ_VHOST"],
    credentials=pika.PlainCredentials(os.environ["RABBITMQ_USER"], os.environ["RABBITMQ_PASSWORD"]),
)
BODY = b'{"probe": "check-isolation"}'


def probe(name: str, action) -> None:  # type: ignore[no-untyped-def]
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.confirm_delivery()
    try:
        action(channel)
        print(f"{name} ALLOWED")
    except pika.exceptions.ChannelClosedByBroker as exc:
        print(f"{name} {exc.reply_code} {exc.reply_text.split(' - ')[0]}")
    finally:
        if connection.is_open:
            connection.close()


def publish(exchange: str, routing_key: str):  # type: ignore[no-untyped-def]
    return lambda ch: ch.basic_publish(exchange, routing_key, BODY, mandatory=True)


for exchange in ("core-to-o1", "o1-to-core", "o1-to-ro", "o2-to-ro"):
    probe(f"publish:{exchange}", publish(exchange, exchange))
probe("publish:default-exchange->o1-to-ro", publish("", "o1-to-ro"))
probe("publish:default-exchange->ro-to-o1", publish("", "ro-to-o1"))
for queue in ("core-to-o1", "o1-to-core", "ro-to-o1", "o1-to-ro.dlq"):
    probe(f"consume:{queue}", lambda ch, q=queue: ch.basic_get(q))
probe("declare:queue", lambda ch: ch.queue_declare("sneaky", durable=False))
probe("declare:exchange", lambda ch: ch.exchange_declare("sneaky", "fanout"))
sys.exit(0)
