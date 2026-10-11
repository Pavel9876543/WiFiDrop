"""Local HTTP URL, optional mDNS and QR for router and hotspot modes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import tempfile
from pathlib import Path

import idna
import qrcode
from zeroconf import IPVersion, ServiceInfo, Zeroconf
from zeroconf._services.info import AddressResolverIPv4

from app.config.settings import PROJECT_ROOT, Settings
from app.hotspot.mobile_windows import detect_mobile_hotspot
from app.hotspot.windows import ensure_firewall_rules_with_elevation
from app.utils.local_name import domain_hostname
from app.utils.network import get_preferred_local_ipv4_address, select_router_ip

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
                    self.settings.port,
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
        ip_url = f"http://{ip}:{self.settings.port}/"
        domain_url = ""
        if self.settings.local_domain:
            hostname = domain_hostname(
                self.settings.local_domain, self.settings.local_domain_method
            )
            if self.settings.local_domain_method == "mdns":
                try:
                    self._announce(hostname, ip)
                    domain_url = f"http://{hostname}:{self.settings.port}/"
                except Exception as exc:
                    self.close()
                    print(f"[WiFiDrop] mDNS недоступен: {exc}. Используется IP-адрес.", flush=True)
            else:
                # Never present an unverified router DNS name as available.
                try:
                    addresses = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
                    if {item[4][0] for item in addresses} != {ip}:
                        raise ValueError("DNS-имя не указывает только на выбранный IP компьютера")
                    domain_url = f"http://{hostname}:{self.settings.port}/"
                except (OSError, ValueError) as exc:
                    print(
                        f"[WiFiDrop] Настройте DNS роутера для {hostname}: {exc}. QR по IP.",
                        flush=True,
                    )
        url = domain_url or ip_url
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
                f"[WiFiDrop] Домен: http://{display}:{self.settings.port}/"
                + ("" if domain_url else " (недоступен; используйте IP)"),
                flush=True,
            )
        payload = {"ip_url": ip_url, "domain_url": domain_url, "url": url, "qr_path": qr_path}
        print(ACCESS_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)
        return payload

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
            port=self.settings.port,
            properties={"path": "/"},
            server=hostname + ".",
        )
        self.zeroconf.register_service(info, allow_name_change=False)
        self.service = info

    def close(self) -> None:
        zc, service = self.zeroconf, self.service
        self.zeroconf = None
        self.service = None
        if zc is not None:
            try:
                if service is not None:
                    zc.unregister_service(service)
            finally:
                zc.close()
