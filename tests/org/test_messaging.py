import pytest

from it42.common.routing import inbound_queues, sender_of


def test_org_queues_and_sender() -> None:
    assert inbound_queues() == ["core-to-o1", "ro-to-o1"]
    assert sender_of("core-to-o1") == "core"
    assert sender_of("ro-to-o1") == "ro"
    for other in ("core-to-o2", "o1-to-core", "o2-to-core", "ro-to-o2", "o1-to-ro"):
        with pytest.raises(ValueError):
            sender_of(other)
