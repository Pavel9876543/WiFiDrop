from __future__ import annotations

import ipaddress
import socket
import struct
import threading
import time

DHCP_MAGIC = b"\x63\x82\x53\x63"
DISCOVER = 1
OFFER = 2
REQUEST = 3
ACK = 5
NAK = 6


def _options(data: bytes) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    pos = 240
    while pos < len(data):
        code = data[pos]
        pos += 1
        if code == 255:
            break
        if code == 0:
            continue
        if pos >= len(data):
            break
        length = data[pos]
        pos += 1
        if pos + length > len(data):
            break
        result[code] = data[pos : pos + length]
        pos += length
    return result


class CaptiveDhcpServer:
    """Small DHCPv4 server for an isolated WiFiDrop hosted network."""

    def __init__(
        self,
        bind_ip: str,
        gateway_ip: str,
        pool_start: str = "192.168.50.10",
        pool_end: str = "192.168.50.200",
        lease_seconds: int = 3600,
        captive_portal_enabled: bool = True,
    ) -> None:
        self.bind_ip = bind_ip
        self.gateway_ip = gateway_ip
        self.captive_portal_enabled = captive_portal_enabled
        self.pool_start = ipaddress.IPv4Address(pool_start)
        self.pool_end = ipaddress.IPv4Address(pool_end)
        self.lease_seconds = lease_seconds
        self._leases: dict[bytes, tuple[ipaddress.IPv4Address, float]] = {}
        self._stop = threading.Event()
        self._sock: socket.socket | None = None

    def _allocate(self, mac: bytes) -> ipaddress.IPv4Address:
        now = time.time()
        current = self._leases.get(mac)
        if current and current[1] > now:
            return current[0]
        used = {ip for ip, expires in self._leases.values() if expires > now}
        for value in range(int(self.pool_start), int(self.pool_end) + 1):
            candidate = ipaddress.IPv4Address(value)
            if candidate not in used:
                self._leases[mac] = (candidate, now + self.lease_seconds)
                return candidate
        raise RuntimeError("DHCP address pool is exhausted")

    def build_response(self, packet: bytes) -> bytes | None:
        if len(packet) < 244 or packet[0] != 1 or packet[236:240] != DHCP_MAGIC:
            return None
        opts = _options(packet)
        msg_type = opts.get(53, b"\x00")[0]
        if msg_type not in (DISCOVER, REQUEST):
            return None
        xid = packet[4:8]
        flags = packet[10:12]
        chaddr = packet[28:44]
        hlen = min(packet[2], 16)
        mac = chaddr[:hlen]
        offered = self._allocate(mac)
        reply_type = OFFER if msg_type == DISCOVER else ACK

        fixed = bytearray(236)
        fixed[0] = 2
        fixed[1] = packet[1]
        fixed[2] = packet[2]
        fixed[3] = 0
        fixed[4:8] = xid
        fixed[10:12] = flags
        fixed[16:20] = offered.packed
        fixed[20:24] = socket.inet_aton(self.gateway_ip)
        fixed[28:44] = chaddr

        options = bytearray(DHCP_MAGIC)
        options += bytes([53, 1, reply_type])
        options += bytes([54, 4]) + socket.inet_aton(self.gateway_ip)
        options += bytes([1, 4]) + socket.inet_aton("255.255.255.0")
        options += bytes([3, 4]) + socket.inet_aton(self.gateway_ip)
        if self.captive_portal_enabled:
            options += bytes([6, 4]) + socket.inet_aton(self.gateway_ip)
        options += bytes([51, 4]) + struct.pack("!I", self.lease_seconds)
        if self.captive_portal_enabled:
            captive_url = f"http://{self.gateway_ip}/.well-known/captive-portal"
            options += bytes([114, len(captive_url)])
            options += captive_url.encode("ascii")
        options += b"\xff"
        return bytes(fixed) + bytes(options)

    def serve_forever(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 67))
        sock.settimeout(0.5)
        self._sock = sock
        try:
            while not self._stop.is_set():
                try:
                    packet, _ = sock.recvfrom(4096)
                except TimeoutError:
                    continue
                response = self.build_response(packet)
                if response:
                    sock.sendto(response, ("255.255.255.255", 68))
        finally:
            sock.close()
            self._sock = None

    def stop(self) -> None:
        self._stop.set()
