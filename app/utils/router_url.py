"""Адрес API явно выбранного локального роутера."""

from ipaddress import IPv4Address, IPv4Network
from urllib.parse import urlsplit

LAN_NETWORKS = tuple(IPv4Network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_ipv4(value: str) -> str:
    address = IPv4Address(value)
    if not any(address in network for network in LAN_NETWORKS):
        raise ValueError("Укажите IPv4 из локальной сети: 10.x, 172.16–31.x или 192.168.x")
    return str(address)


def normalize_router_url(value: str) -> str:
    url = urlsplit(value.strip())
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Адрес API: http(s)://IP-роутера[:порт], без логина и пути")
    ip = lan_ipv4(url.hostname)
    port = url.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Неверный порт API")
    return f"{url.scheme}://{ip}" + (f":{port}" if port else "")


def http_url(host: str, port: int) -> str:
    return f"http://{host}" + (f":{port}" if port != 80 else "") + "/"
