import socket
from unittest.mock import MagicMock

import pytest

from app.utils.network import get_local_ipv4_addresses


def test_local_addresses_exclude_loopback(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.42", 0)),
        ],
    )

    assert get_local_ipv4_addresses() == ["192.168.1.42"]


def test_preferred_local_address_uses_route(monkeypatch) -> None:
    from app.utils.network import get_preferred_local_ipv4_address

    class FakeSocket:
        def connect(self, _address):
            return None

        def getsockname(self):
            return ("192.168.50.7", 12345)

        def close(self):
            return None

    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: FakeSocket())
    assert get_preferred_local_ipv4_address() == "192.168.50.7"


def test_router_ip_uses_route_to_configured_router(monkeypatch):
    from app.utils import network

    monkeypatch.setattr(network, "get_router_interfaces", lambda: [
        ("Ethernet", "192.168.2.20"), ("Wi-Fi", "192.168.1.20"),
    ])
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.getsockname.return_value = ("192.168.1.20", 12345)
    monkeypatch.setattr(socket, "socket", lambda *_: sock)
    assert network.select_router_ip(None, router_ip="192.168.1.1") == "192.168.1.20"
    sock.connect.assert_called_once_with(("192.168.1.1", 53))
    assert network.select_router_ip("192.168.2.20", router_ip="192.168.1.1") == "192.168.2.20"


def test_router_route_failure_requires_explicit_address(monkeypatch):
    from app.utils import network

    monkeypatch.setattr(network, "get_router_interfaces", lambda: [("Wi-Fi", "192.168.1.20")])
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.connect.side_effect = OSError("unreachable")
    monkeypatch.setattr(socket, "socket", lambda *_: sock)
    with pytest.raises(ValueError, match="Нет маршрута"):
        network.select_router_ip(None, router_ip="192.168.2.1")
