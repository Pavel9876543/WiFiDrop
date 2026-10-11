"""Local HTTP URL, optional mDNS and QR for router and hotspot modes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

import idna
import qrcode
from zeroconf import IPVersion, ServiceInfo, Zeroconf
from zeroconf._services.info import AddressResolverIPv4

from app.config.settings import PROJECT_ROOT, Settings
from app.hotspot.mobile_windows import detect_mobile_hotspot
from app.hotspot.windows import ensure_firewall_rules_with_elevation
from app.services.access_diagnostics import check_http, diagnose_access
from app.utils.local_name import domain_hostname
from app.utils.network import get_preferred_local_ipv4_address, select_router_ip
from app.utils.router_url import http_url

ACCESS_PREFIX = "[WiFiDrop] ACCESS "
QR_PATH = PROJECT_ROOT / "wifidrop_qr.png"


def save_qr(url: str, path: Path = QR_PATH) -> None:
    """Replace the previous PNG only after the complete new image is written."""
    fd, temporary = tempfile.mkstemp(prefix=".wifidrop_qr.", suffix=".png", dir=path.parent)
    os.close(fd)
    try:
        qrcode.make(url).save(temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class RouterAccess:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.zeroconf: Zeroconf | None = None
        self.service: ServiceInfo | None = None
        self.closed = threading.Event()
        self.payload: dict[str, str] = {}
        self.hostname: str | None = None

    def start(self) -> dict[str, str]:
        if self.settings.connection_mode == "router":
            ip = select_router_ip(self.settings.router_ip, self.settings.host)
        else:
            ip = self.settings.access_ip
            if not ip:
                if self.settings.hotspot_enabled:
                    ip = self.settings.hotspot_gateway_ip
                else:
                    info = detect_mobile_hotspot()
                    ip = info.ipv4 if info else get_preferred_local_ipv4_address()
            ip = select_router_ip(ip, self.settings.host)
        if os.name == "nt":
            try:
                ready = ensure_firewall_rules_with_elevation(
                    self.settings.effective_port,
                    access_only=True,
                    mdns=bool(
                        self.settings.local_domain and self.settings.local_domain_method == "mdns"
                    ),
                )
            except OSError as exc:
                ready = False
                print(f"[WiFiDrop] Ошибка настройки брандмауэра: {exc}", flush=True)
            if not ready:
                print(
                    "[WiFiDrop] Не удалось разрешить HTTP/mDNS в брандмауэре Windows. "
                    "Доступ с других устройств может быть заблокирован.",
                    flush=True,
                )
        ip_url = http_url(ip, self.settings.effective_port)
        domain_url = ""
        if self.settings.local_domain:
            hostname = domain_hostname(
                self.settings.local_domain, self.settings.local_domain_method
            )
            self.hostname = hostname
            if self.settings.local_domain_method == "mdns":
                try:
                    self._announce(hostname, ip)
                    domain_url = http_url(hostname, self.settings.effective_port)
                except Exception as exc:
                    self._close_mdns()
                    print(f"[WiFiDrop] mDNS недоступен: {exc}. Используется IP-адрес.", flush=True)
            else:
                domain_url = http_url(hostname, self.settings.effective_port)
        # Объявление mDNS не доказывает ни DNS-ответ, ни доступность HTTP.
        url = ip_url
        qr_path = ""
        try:
            save_qr(ip_url)
            qr_path = str(QR_PATH)
        except OSError as exc:
            # Remove an old QR so it cannot silently point to another session.
            with contextlib.suppress(OSError):
                QR_PATH.unlink(missing_ok=True)
            print(f"[WiFiDrop] Не удалось сохранить QR: {exc}", flush=True)
        print(f"[WiFiDrop] IP: {ip_url}", flush=True)
        if self.settings.local_domain:
            display = idna.decode(hostname)
            print(
                f"[WiFiDrop] Домен: {http_url(display, self.settings.effective_port)}"
                + (" (ожидает проверки)" if domain_url else " (недоступен; используйте IP)"),
                flush=True,
            )
        payload = {"ip_url": ip_url, "domain_url": domain_url, "url": url, "qr_path": qr_path}
        if self.settings.local_domain:
            payload["domain_status"] = "Имя объявлено/задано; DNS и HTTP ещё не проверены"
        self.payload = payload
        print(ACCESS_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)
        return payload

    def verify(self) -> None:
        """Вызывается после запуска HTTP; до bind проверять соединение нельзя."""
        if not self.payload or self.closed.is_set():
            return
        message = ""
        for _ in range(8):
            if self.closed.is_set():
                return
            try:
                check_http(self.payload["ip_url"])
                break
            except ValueError as exc:
                message = str(exc)
                if self.closed.wait(0.25):
                    return
        else:
            self._verification_result(False, message)
            return
        try:
            router_ip = (
                urlsplit(self.settings.router_api_url).hostname
                if self.settings.router_api_url
                else None
            )
            message = diagnose_access(
                self.payload["ip_url"], self.hostname, self.settings.local_domain_method, router_ip
            )
        except (OSError, ValueError) as exc:
            self._verification_result(False, str(exc))
        else:
            self._verification_result(True, message)

    def _verification_result(self, ok: bool, message: str) -> None:
        if self.closed.is_set():
            return
        self.payload["domain_status"] = message
        if not ok:
            self.payload["domain_url"] = ""
        elif self.hostname:
            self.payload["domain_url"] = http_url(self.hostname, self.settings.effective_port)
        self.payload["url"] = self.payload["domain_url"] or self.payload["ip_url"]
        print(f"[WiFiDrop] Проверка соединения: {message}", flush=True)
        print(ACCESS_PREFIX + json.dumps(self.payload, ensure_ascii=False), flush=True)

    def _announce(self, hostname: str, ip: str) -> None:
        self.zeroconf = Zeroconf(interfaces=[ip], ip_version=IPVersion.V4Only)
        # Check the host A record as well as the service instance conflict.
        resolver = AddressResolverIPv4(hostname + ".")
        resolver.request(self.zeroconf, timeout=1200)
        existing = set(resolver.parsed_addresses())
        if existing and existing != {ip}:
            raise ValueError("Имя уже используется другим устройством в этой сети")
        info = ServiceInfo(
            "_http._tcp.local.",
            f"WiFiDrop-{hashlib.sha256(hostname.encode()).hexdigest()[:16]}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=self.settings.effective_port,
            properties={"path": "/"},
            server=hostname + ".",
        )
        self.zeroconf.register_service(info, allow_name_change=False)
        self.service = info

    def close(self) -> None:
        self.closed.set()
        self._close_mdns()

    def _close_mdns(self) -> None:
        zc, service = self.zeroconf, self.service
        self.zeroconf = None
        self.service = None
        if zc is not None:
            try:
                if service is not None:
                    zc.unregister_service(service)
            finally:
                zc.close()
