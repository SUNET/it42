"""The event envelope exchanged between zones."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from django.utils import timezone


class RejectEvent(Exception):
    """The event is invalid or not allowed for this sender. It is never retried and
    goes straight to the dead-letter queue."""


@dataclass(frozen=True)
class Envelope:
    type: str
    payload: dict[str, Any]
    version: int = 1
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=timezone.now)
    application_id: uuid.UUID | None = None
    grant_id: uuid.UUID | None = None
    seq: int | None = None

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "id": str(self.id),
                "type": self.type,
                "version": self.version,
                "occurred_at": self.occurred_at.isoformat(),
                "application_id": str(self.application_id) if self.application_id else None,
                "grant_id": str(self.grant_id) if self.grant_id else None,
                "seq": self.seq,
                "payload": self.payload,
            },
            separators=(",", ":"),
        ).encode()

    @classmethod
    def from_json(cls, body: bytes) -> "Envelope":
        try:
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
                raise ValueError("envelope must be an object with an object payload")
            if not isinstance(data.get("type"), str) or not isinstance(data.get("version"), int):
                raise ValueError("type must be a string and version an integer")
            seq = data.get("seq")
            if seq is not None and (not isinstance(seq, int) or isinstance(seq, bool) or seq < 1):
                raise ValueError("seq must be a positive integer")
            envelope = cls(
                id=uuid.UUID(data["id"]),
                type=data["type"],
                version=data["version"],
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                application_id=_uuid_or_none(data.get("application_id")),
                grant_id=_uuid_or_none(data.get("grant_id")),
                seq=seq,
                payload=data["payload"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RejectEvent(f"malformed envelope: {exc}") from exc
        envelope._check_payload_matches()
        return envelope

    def _check_payload_matches(self) -> None:
        """Identifiers repeated in the payload must agree with the envelope."""
        checks = {
            "application_id": self.application_id,
            "grant_public_id": self.grant_id,
            "seq": self.seq,
        }
        for key, expected in checks.items():
            if key in self.payload:
                value = self.payload[key]
                if key != "seq":
                    try:
                        value = _uuid_or_none(value)
                    except ValueError as exc:
                        raise RejectEvent(f"payload {key} is not a valid id") from exc
                if value != expected:
                    raise RejectEvent(f"payload {key} does not match the envelope")


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("ids must be strings")
    return uuid.UUID(value)
