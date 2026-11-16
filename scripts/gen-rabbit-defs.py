#!/usr/bin/env python3
"""Generate rabbitmq/definitions.json from the env files.

Every org gets two quorum queues to and from the core and two to and from the
research organisation (RO) zone, one per direction, each fed by a direct exchange
with the same name. The core and the RO zone have no link. Users may write only to
their outbound exchanges and read only from their inbound queues, and nobody may
configure anything, so the default exchange (which can route to any queue by name)
is never writable.

Run from the repository root:  python3 scripts/gen-rabbit-defs.py
"""

import base64
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VHOST = "/it42"
ORGS = ("o1", "o2", "o3", "o4", "o5")
RO = "ro"
DLX = "it42.dlx"
DELIVERY_LIMIT = 5


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def rabbit_sha256(password: str) -> str:
    """RabbitMQ's rabbit_password_hashing_sha256: base64(salt + sha256(salt + pw))."""
    salt = secrets.token_bytes(4)
    digest = hashlib.sha256(salt + password.encode()).digest()
    return base64.b64encode(salt + digest).decode()


def user(name: str, password: str, tags: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "password_hash": rabbit_sha256(password),
        "hashing_algorithm": "rabbit_password_hashing_sha256",
        "tags": tags,
        "limits": {},
    }


def permission(name: str, configure: str, write: str, read: str) -> dict[str, str]:
    return {"user": name, "vhost": VHOST, "configure": configure, "write": write, "read": read}


def queue(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "vhost": VHOST,
        "durable": True,
        "auto_delete": False,
        "arguments": {"x-queue-type": "quorum", **arguments},
    }


def exchange(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "vhost": VHOST,
        "type": "direct",
        "durable": True,
        "auto_delete": False,
        "internal": False,
        "arguments": {},
    }


def binding(source: str, destination: str, routing_key: str) -> dict[str, Any]:
    return {
        "source": source,
        "vhost": VHOST,
        "destination": destination,
        "destination_type": "queue",
        "routing_key": routing_key,
        "arguments": {},
    }


def exactly(names: list[str]) -> str:
    """A permission regex that matches exactly these resource names."""
    return "^(" + "|".join(re.escape(name) for name in names) + ")$"


def build(env_dir: Path) -> dict[str, Any]:
    admin = read_env(env_dir / "rabbitmq.env")
    zone_users = {}
    for zone in ("core", *ORGS, RO):
        values = read_env(env_dir / f"{zone}-mq.env")
        if values.get("RABBITMQ_USER") != zone:
            raise SystemExit(f"env/{zone}-mq.env must set RABBITMQ_USER={zone}")
        zone_users[zone] = values["RABBITMQ_PASSWORD"]

    flows = [
        name
        for org in ORGS
        for name in (f"core-to-{org}", f"{org}-to-core", f"{org}-to-{RO}", f"{RO}-to-{org}")
    ]

    return {
        "rabbit_version": "4.3.6",
        "vhosts": [{"name": VHOST}],
        "users": [
            user(admin["RABBITMQ_ADMIN_USER"], admin["RABBITMQ_ADMIN_PASSWORD"], ["administrator"]),
            *(user(zone, password, []) for zone, password in zone_users.items()),
        ],
        "permissions": [
            permission(admin["RABBITMQ_ADMIN_USER"], ".*", ".*", ".*"),
            permission(
                "core",
                "^$",
                exactly([f"core-to-{o}" for o in ORGS]),
                exactly([f"{o}-to-core" for o in ORGS]),
            ),
            *(
                permission(
                    o,
                    "^$",
                    exactly([f"{o}-to-core", f"{o}-to-{RO}"]),
                    exactly([f"core-to-{o}", f"{RO}-to-{o}"]),
                )
                for o in ORGS
            ),
            permission(
                RO,
                "^$",
                exactly([f"{RO}-to-{o}" for o in ORGS]),
                exactly([f"{o}-to-{RO}" for o in ORGS]),
            ),
        ],
        "exchanges": [exchange(DLX), *(exchange(name) for name in flows)],
        "queues": [
            *(
                queue(
                    name,
                    {
                        "x-delivery-limit": DELIVERY_LIMIT,
                        "x-dead-letter-exchange": DLX,
                        "x-dead-letter-routing-key": f"{name}.dlq",
                    },
                )
                for name in flows
            ),
            *(queue(f"{name}.dlq", {}) for name in flows),
        ],
        "bindings": [
            *(binding(name, name, name) for name in flows),
            *(binding(DLX, f"{name}.dlq", f"{name}.dlq") for name in flows),
        ],
        "topic_permissions": [],
        "parameters": [],
        "policies": [],
        "global_parameters": [],
    }


def main() -> int:
    env_dir = ROOT / "env"
    target = ROOT / "rabbitmq" / "definitions.json"
    definitions = build(env_dir)
    target.write_text(json.dumps(definitions, indent=2) + "\n")
    # Read by the rabbitmq user inside the container; it holds only hashes.
    os.chmod(target, 0o644)
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
