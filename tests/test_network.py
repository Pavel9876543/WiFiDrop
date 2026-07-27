import socket

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
