"""Run inside a worker: publish one event on one of the zone's own outbound exchanges.

Usage: forge.py <exchange>  -- the envelope is read from stdin.
Prints the message id. Publishing is allowed (it's the zone's own exchange); what the
receiving zone does with the event is the point of the test.
"""

import json
import os
import sys

import pika

envelope = json.loads(sys.stdin.read())
exchange = sys.argv[1]
params = pika.ConnectionParameters(
    host=os.environ["RABBITMQ_HOST"],
    virtual_host=os.environ["RABBITMQ_VHOST"],
    credentials=pika.PlainCredentials(os.environ["RABBITMQ_USER"], os.environ["RABBITMQ_PASSWORD"]),
)
connection = pika.BlockingConnection(params)
channel = connection.channel()
channel.confirm_delivery()
channel.basic_publish(
    exchange,
    exchange,
    json.dumps(envelope).encode(),
    pika.BasicProperties(
        content_type="application/json",
        delivery_mode=pika.DeliveryMode.Persistent,
        message_id=envelope["id"],
        type=envelope["type"],
    ),
    mandatory=True,
)
connection.close()
print(envelope["id"])
