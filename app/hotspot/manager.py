from __future__ import annotations

import platform
import socket
import threading
from dataclasses import dataclass

from app.hotspot.dhcp import CaptiveDhcpServer
from app.hotspot.dns import CaptiveDnsServer
from app.hotspot.windows import (
    HotspotError,
    configure_adapter,
    configure_and_start_hosted_network,
    ensure_firewall_rules,
    is_windows_admin,
    open_mobile_hotspot_settings,
    stop_hosted_network,
)


@dataclass(frozen=True)
class HotspotInfo:
    ssid: str
    password: str
    gateway_ip: str
    adapter_name: str


def _assert_port_available(host: str, port: int, sock_type: int) -> None:
    sock = socket.socket(socket.AF_INET, sock_type)
    try:
        sock.bind((host, port))
    except OSError as exc:
        protocol = "UDP" if sock_type == socket.SOCK_DGRAM else "TCP"
        raise HotspotError(f"Required {protocol} port {port} is unavailable on {host}: {exc}") from exc
    finally:
        sock.close()


class WindowsCaptiveHotspot:
    def __init__(self, ssid: str, password: str, gateway_ip: str, app_port: int) -> None:
        self.ssid = ssid
        self.password = password
        self.gateway_ip = gateway_ip
        self.app_port = app_port
        prefix = gateway_ip.rsplit(".", 1)[0]
        self.dhcp = CaptiveDhcpServer(gateway_ip, gateway_ip, f"{prefix}.10", f"{prefix}.200")
        self.dns = CaptiveDnsServer(gateway_ip, gateway_ip)
        self._threads: list[threading.Thread] = []
        self._started = False

    def start(self) -> HotspotInfo:
        if platform.system() != "Windows":
            raise HotspotError("Automatic WiFiDrop hotspot mode is implemented for Windows only")
        if not is_windows_admin():
            raise HotspotError("Administrator privileges are required for hotspot, DHCP, DNS and firewall setup")

        try:
            adapter = configure_and_start_hosted_network(self.ssid, self.password)
            configure_adapter(adapter.name, self.gateway_ip)
            _assert_port_available("0.0.0.0", 67, socket.SOCK_DGRAM)
            _assert_port_available(self.gateway_ip, 53, socket.SOCK_DGRAM)
            _assert_port_available("0.0.0.0", 80, socket.SOCK_STREAM)
            ensure_firewall_rules(self.app_port)
            for name, server in (("wifidrop-dhcp", self.dhcp), ("wifidrop-dns", self.dns)):
                thread = threading.Thread(target=server.serve_forever, name=name, daemon=True)
                thread.start()
                self._threads.append(thread)
            self._started = True
            return HotspotInfo(self.ssid, self.password, self.gateway_ip, adapter.name)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self.dhcp.stop()
        self.dns.stop()
        if self._started:
            stop_hosted_network()
        self._started = False

    @staticmethod
    def open_windows_fallback() -> None:
        open_mobile_hotspot_settings()
