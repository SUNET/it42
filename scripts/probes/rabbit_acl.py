"""Run inside an org worker: probe RabbitMQ permissions with that org's credentials.

Each probe opens a fresh channel and prints "<name> ALLOWED" or "<name> <code> <text>".
Publishes use publisher confirms so a refusal is reported synchronously.
"""

import os
import sys

import pika
import pika.exceptions

org = os.environ["ORG_SLUG"]
other = "o2" if org == "o1" else "o1"
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


probe(f"publish:{other}-to-core", publish(f"{other}-to-core", f"{other}-to-core"))
probe(f"publish:core-to-{org}", publish(f"core-to-{org}", f"core-to-{org}"))
probe(f"publish:core-to-{other}", publish(f"core-to-{other}", f"core-to-{other}"))
probe(f"publish:default-exchange->{org}-to-core", publish("", f"{org}-to-core"))
probe(f"publish:default-exchange->core-to-{other}", publish("", f"core-to-{other}"))
probe(f"publish:{other}-to-ro", publish(f"{other}-to-ro", f"{other}-to-ro"))
probe(f"publish:ro-to-{org}", publish(f"ro-to-{org}", f"ro-to-{org}"))
probe(f"consume:core-to-{other}", lambda ch: ch.basic_get(f"core-to-{other}"))
probe(f"consume:ro-to-{other}", lambda ch: ch.basic_get(f"ro-to-{other}"))
probe(f"consume:{org}-to-ro", lambda ch: ch.basic_get(f"{org}-to-ro"))
probe(f"consume:{org}-to-core", lambda ch: ch.basic_get(f"{org}-to-core"))
probe(f"consume:core-to-{org}.dlq", lambda ch: ch.basic_get(f"core-to-{org}.dlq"))
probe("declare:queue", lambda ch: ch.queue_declare("sneaky", durable=False))
probe("declare:exchange", lambda ch: ch.exchange_declare("sneaky", "fanout"))
sys.exit(0)
