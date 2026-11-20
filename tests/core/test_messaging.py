import json
import uuid
from typing import Any

import pytest
from django.db import transaction

from it42.common.events import Envelope, RejectEvent
from it42.common.inbox import process
from it42.common.management.commands.relay_outbox import relay_batch
from it42.common.models import OutboxEvent, ProcessedEvent
from it42.common.outbox import emit
from it42.common.routing import inbound_queues, sender_of


def body(**overrides: Any) -> bytes:
    data: dict[str, Any] = json.loads(Envelope(type="system.pong", payload={}).to_json())
    data.update(overrides)
    return json.dumps(data).encode()


def test_envelope_round_trip() -> None:
    app_id = uuid.uuid4()
    envelope = Envelope(type="x", payload={"application_id": str(app_id)}, application_id=app_id)
    assert Envelope.from_json(envelope.to_json()) == envelope


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        body(payload=[]),
        body(id="nope"),
        body(seq=0),
        body(seq="1"),
        body(seq=True),
        body(version="1"),
    ],
)
def test_malformed_envelopes_are_rejected(raw: bytes) -> None:
    with pytest.raises(RejectEvent):
        Envelope.from_json(raw)


def test_payload_ids_must_match_envelope() -> None:
    raw = body(application_id=str(uuid.uuid4()), payload={"application_id": str(uuid.uuid4())})
    with pytest.raises(RejectEvent, match="does not match"):
        Envelope.from_json(raw)
    raw = body(seq=3, payload={"seq": 4})
    with pytest.raises(RejectEvent, match="does not match"):
        Envelope.from_json(raw)


def test_core_queues_and_sender() -> None:
    assert inbound_queues() == [
        "o1-to-core",
        "o2-to-core",
        "o3-to-core",
        "o4-to-core",
        "o5-to-core",
        "ro-to-core",
    ]
    assert sender_of("ro-to-core") == "ro"
    assert sender_of("o1-to-core") == "o1"
    assert sender_of("o2-to-core") == "o2"
    assert sender_of("o3-to-core") == "o3"
    assert sender_of("o4-to-core") == "o4"
    assert sender_of("o5-to-core") == "o5"
    with pytest.raises(ValueError):
        sender_of("core-to-o1")


@pytest.mark.django_db(transaction=True)
def test_emit_requires_a_transaction() -> None:
    with pytest.raises(RuntimeError):
        emit("core-to-o1", "system.ping", {})


@pytest.mark.django_db(transaction=True)
def test_emit_rolls_back_with_the_state_change() -> None:
    with pytest.raises(ZeroDivisionError), transaction.atomic():
        emit("core-to-o1", "system.ping", {})
        1 / 0  # noqa: B018
    assert not OutboxEvent.objects.exists()


@pytest.mark.django_db
def test_duplicate_event_is_processed_once() -> None:
    raw = body()
    assert process(raw, "o1-to-core") is True
    assert process(raw, "o1-to-core") is False
    assert ProcessedEvent.objects.count() == 1


@pytest.mark.django_db
def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(RejectEvent, match="no handler"):
        process(body(type="nope"), "o1-to-core")
    with pytest.raises(RejectEvent, match="no handler"):
        process(body(version=2), "o1-to-core")
    assert not ProcessedEvent.objects.exists()


@pytest.mark.django_db
def test_ping_is_answered_through_the_outbox() -> None:
    process(body(type="system.ping"), "o2-to-core")
    reply = OutboxEvent.objects.get()
    assert (reply.exchange, reply.type) == ("core-to-o2", "system.pong")


@pytest.mark.django_db
def test_ping_on_the_one_way_ro_route_is_rejected_without_a_reply() -> None:
    with pytest.raises(RejectEvent, match="one-way"):
        process(body(type="system.ping"), "ro-to-core")
    assert not OutboxEvent.objects.exists()
    assert not ProcessedEvent.objects.exists()


class FakeChannel:
    def __init__(self, fail_on: int | None = None) -> None:
        self.published: list[dict[str, Any]] = []
        self.fail_on = fail_on

    def basic_publish(
        self,
        exchange: str,
        routing_key: str,
        body: bytes,
        properties: Any = None,
        mandatory: bool = False,
    ) -> None:
        if self.fail_on is not None and len(self.published) == self.fail_on:
            raise RuntimeError("broker said no")
        self.published.append(
            {"exchange": exchange, "routing_key": routing_key, "properties": properties}
        )


@pytest.mark.django_db
def test_relay_publishes_in_order_and_marks_rows() -> None:
    with transaction.atomic():
        first = emit("core-to-o1", "system.ping", {})
        second = emit("core-to-o2", "system.ping", {})
    channel = FakeChannel()
    assert relay_batch(channel) == 2
    assert [p["properties"].message_id for p in channel.published] == [
        str(first.id),
        str(second.id),
    ]
    assert channel.published[0]["exchange"] == "core-to-o1"
    assert channel.published[0]["properties"].delivery_mode == 2
    assert not OutboxEvent.objects.filter(published_at__isnull=True).exists()
    assert relay_batch(channel) == 0


@pytest.mark.django_db
def test_relay_failure_keeps_the_row_and_records_the_error() -> None:
    with transaction.atomic():
        emit("core-to-o1", "system.ping", {})
        emit("core-to-o1", "system.ping", {})
    channel = FakeChannel(fail_on=1)
    with pytest.raises(RuntimeError):
        relay_batch(channel)
    pending = OutboxEvent.objects.get(published_at__isnull=True)
    assert pending.attempts == 1
    assert "broker said no" in pending.last_error
