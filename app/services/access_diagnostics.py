"""Проверки DNS/mDNS и HTTP с ограниченным временем ожидания."""

from __future__ import annotations

import socket
import time
from urllib.parse import urlsplit

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import dns.resolver
import httpx


def _addresses(response, hostname: str) -> set[str]:
    name = hostname.lower().rstrip(".") + "."
    if not response.flags & dns.flags.QR or response.rcode() != dns.rcode.NOERROR:
        return set()
    return {
        item.address
        for record in (*response.answer, *response.additional)
        if record.name.to_text().lower() == name and record.rdtype == dns.rdatatype.A
        for item in record
    }


def resolve_router_name(hostname: str, router_ip: str | None = None) -> set[str]:
    try:
        if router_ip:
            query = dns.message.make_query(hostname + ".", "A")
            response = dns.query.udp(query, router_ip, timeout=2)
            if response.flags & dns.flags.TC:
                response = dns.query.tcp(query, router_ip, timeout=2)
            return _addresses(response, hostname)
        answer = dns.resolver.resolve(hostname + ".", "A", lifetime=2, search=False)
        return {item.address for item in answer}
    except (dns.exception.DNSException, OSError) as exc:
        raise ValueError("DNS не ответил или запись имени отсутствует") from exc


def resolve_mdns_name(hostname: str, local_ip: str, timeout: float = 2) -> set[str]:
    # Отдельный сокет проверяет ответ на обычный запрос A, а не кэш нашего объявления.
    query = dns.message.make_query(hostname + ".", "A")
    query.flags = 0
    found: set[str] = set()
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((local_ip, 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        sock.sendto(query.to_wire(), ("224.0.0.251", 5353))
        while time.monotonic() < deadline:
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                packet, _ = sock.recvfrom(65535)
            except TimeoutError:
                break
            try:
                response = dns.message.from_wire(packet)
            except dns.exception.DNSException:
                continue
            if response.id == query.id:
                found.update(_addresses(response, hostname))
    if not found:
        raise ValueError("Нет ответа mDNS на выбранном адаптере (UDP 5353)")
    return found


def check_http(ip_url: str, hostname: str | None = None) -> None:
    headers = {}
    if hostname:
        port = urlsplit(ip_url).port or 80
        headers["Host"] = hostname + (f":{port}" if port != 80 else "")
    try:
        # Системный proxy не должен перенаправлять запрос к локальному компьютеру.
        with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
            health = client.get(ip_url + "api/health", headers=headers)
            if health.status_code != 200 or health.json() != {"status": "ok"}:
                raise ValueError("На выбранном IP/порту не отвечает WiFiDrop")
            home = client.get(ip_url, headers=headers)
            if home.status_code != 200 or not home.content.strip():
                raise ValueError("Сайт не отправил непустую страницу HTTP 200")
    except httpx.HTTPError as exc:
        raise ValueError("Нет HTTP-соединения с выбранным IP/портом компьютера") from exc


def diagnose_access(ip_url: str, hostname: str | None, method: str, router_ip: str | None):
    ip = urlsplit(ip_url).hostname
    if not ip:
        raise ValueError("Неверный адрес компьютера")
    check_http(ip_url, hostname)
    if not hostname:
        return "HTTP: сервер отвечает по IP. Домен не задан."
    addresses = (
        resolve_mdns_name(hostname, ip)
        if method == "mdns"
        else resolve_router_name(hostname, router_ip)
    )
    if addresses != {ip}:
        actual = ", ".join(sorted(addresses)) or "нет записи"
        raise ValueError(f"{hostname} → {actual}; должен указывать только на {ip}")
    source = "mDNS" if method == "mdns" else "DNS роутера" if router_ip else "DNS компьютера"
    return (
        f"{source}: {hostname} → {ip}. HTTP отвечает с этим именем. "
        "Проверено на компьютере; доступ с телефона требует проверки на телефоне."
    )
