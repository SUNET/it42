import base64
import hashlib
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_rabbit_defs", ROOT / "scripts/gen-rabbit-defs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def definitions(tmp_path: Path) -> dict:
    (tmp_path / "rabbitmq.env").write_text("RABBITMQ_ADMIN_USER=admin\nRABBITMQ_ADMIN_PASSWORD=a\n")
    for zone in ("core", "o1", "o2", "o3", "o4", "o5", "ro"):
        (tmp_path / f"{zone}-mq.env").write_text(
            f"RABBITMQ_USER={zone}\nRABBITMQ_PASSWORD=pw-{zone}\n"
        )
    return load_generator().build(tmp_path)


def can(definitions: dict, user: str, kind: str, resource: str) -> bool:
    perm = next(p for p in definitions["permissions"] if p["user"] == user)
    return re.search(perm[kind], resource) is not None


def test_no_guest_user(definitions: dict) -> None:
    assert "guest" not in {u["name"] for u in definitions["users"]}


@pytest.mark.parametrize("user", ["core", "o1", "o2", "o3", "o4", "o5", "ro"])
def test_zone_users_cannot_configure_or_use_default_exchange(definitions: dict, user: str) -> None:
    # "^$" is RabbitMQ's documented "deny all"; it only matches the empty name of
    # the default exchange, which RabbitMQ never lets anyone declare or delete.
    for resource in ("amq.default", "o1-to-core", "core-to-o1", "anything"):
        assert not can(definitions, user, "configure", resource)
    # The default exchange is named "" (amq.default in the management API).
    assert not can(definitions, user, "write", "")
    assert not can(definitions, user, "write", "amq.default")


def test_org_permissions_are_limited_to_own_queues(definitions: dict) -> None:
    assert can(definitions, "o1", "write", "o1-to-core")
    assert can(definitions, "o1", "write", "o1-to-ro")
    assert can(definitions, "o1", "read", "core-to-o1")
    assert can(definitions, "o1", "read", "ro-to-o1")
    for forbidden in ("o2-to-core", "core-to-o1", "core-to-o2", "it42.dlx", "o2-to-ro", "ro-to-o1"):
        assert not can(definitions, "o1", "write", forbidden)
    for forbidden in (
        "core-to-o2",
        "o1-to-core",
        "o2-to-core",
        "core-to-o1.dlq",
        "ro-to-o2",
        "o1-to-ro",
        "ro-to-o1.dlq",
    ):
        assert not can(definitions, "o1", "read", forbidden)


@pytest.mark.parametrize("org", ["o1", "o2", "o3"])
def test_orgs_cannot_publish_ro_decisions(definitions: dict, org: str) -> None:
    assert not can(definitions, org, "write", "ro-to-core")


def test_ro_permissions_reach_only_the_orgs_and_core_decision_flow(definitions: dict) -> None:
    for org in ("o1", "o2", "o3", "o4", "o5"):
        assert can(definitions, "ro", "write", f"ro-to-{org}")
        assert can(definitions, "ro", "read", f"{org}-to-ro")
    assert can(definitions, "ro", "write", "ro-to-core")
    for forbidden in ("core-to-o1", "o1-to-core", "o1-to-ro", "ro-to-o1.dlq"):
        assert not can(definitions, "ro", "write", forbidden)
    for forbidden in ("core-to-o1", "o1-to-core", "ro-to-o1", "o1-to-ro.dlq"):
        assert not can(definitions, "ro", "read", forbidden)
    # The link is one-way: only RO decisions go directly to core.
    assert not can(definitions, "core", "write", "core-to-ro")
    assert can(definitions, "core", "read", "ro-to-core")
    assert not can(definitions, "core", "read", "o1-to-ro")


def test_core_permissions(definitions: dict) -> None:
    assert can(definitions, "core", "write", "core-to-o1")
    assert can(definitions, "core", "write", "core-to-o2")
    assert not can(definitions, "core", "write", "core-to-o|")
    assert not can(definitions, "core", "write", "o1-to-core")
    assert can(definitions, "core", "read", "o2-to-core")
    assert can(definitions, "core", "read", "ro-to-core")
    assert not can(definitions, "core", "read", "core-to-o1")


def test_queues_are_quorum_with_delivery_limit_and_dlq(definitions: dict) -> None:
    queues = {q["name"]: q["arguments"] for q in definitions["queues"]}
    for name in (
        "core-to-o1",
        "o1-to-core",
        "core-to-o2",
        "o2-to-core",
        "o1-to-ro",
        "ro-to-o2",
        "ro-to-core",
    ):
        args = queues[name]
        assert args["x-queue-type"] == "quorum"
        assert args["x-delivery-limit"] == 5
        assert args["x-dead-letter-exchange"] == "it42.dlx"
        assert args["x-dead-letter-routing-key"] == f"{name}.dlq"
        assert f"{name}.dlq" in queues


def test_password_hash_format(definitions: dict) -> None:
    core = next(u for u in definitions["users"] if u["name"] == "core")
    raw = base64.b64decode(core["password_hash"])
    salt, digest = raw[:4], raw[4:]
    assert digest == hashlib.sha256(salt + b"pw-core").digest()


@pytest.mark.parametrize("org", ["o3", "o4", "o5"])
def test_new_org_routes_and_isolation(definitions: dict, org: str) -> None:
    for peer in ("core", "ro"):
        assert can(definitions, org, "write", f"{org}-to-{peer}")
        assert can(definitions, org, "read", f"{peer}-to-{org}")
        assert can(definitions, peer, "write", f"{peer}-to-{org}")
        assert can(definitions, peer, "read", f"{org}-to-{peer}")
    for other in {"o1", "o2", "o3", "o4", "o5"} - {org}:
        for peer in ("core", "ro"):
            assert not can(definitions, org, "read", f"{peer}-to-{other}")
            assert not can(definitions, org, "write", f"{other}-to-{peer}")
