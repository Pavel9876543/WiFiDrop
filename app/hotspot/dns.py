from __future__ import annotations

import socket
import struct
import threading


class CaptiveDnsServer:
    """Minimal UDP DNS server that resolves every A query to the portal IP.

    This is intentional for an isolated WiFiDrop hotspot: connectivity-check
    hostnames must resolve to the local portal so Android/iOS/Windows can see
    the captive redirect. It must never be exposed on a normal LAN/WAN.
    """

    def __init__(self, bind_ip: str, portal_ip: str, port: int = 53) -> None:
        self.bind_ip = bind_ip
        self.portal_ip = portal_ip
        self.port = port
        self._stop = threading.Event()
        self._sock: socket.socket | None = None

    @staticmethod
    def build_response(packet: bytes, portal_ip: str) -> bytes | None:
        if len(packet) < 12:
            return None
        transaction_id = packet[:2]
        flags, qdcount = struct.unpack("!HH", packet[2:6])
        if qdcount != 1:
            return None

        pos = 12
        while pos < len(packet):
            length = packet[pos]
            pos += 1
            if length == 0:
                break
            if length & 0xC0 or pos + length > len(packet):
                return None
            pos += length
        if pos + 4 > len(packet):
            return None
        qtype, qclass = struct.unpack("!HH", packet[pos : pos + 4])
        question_end = pos + 4

        # NOERROR, authoritative-ish answer, recursion unavailable.
        response_flags = 0x8400
        answer_count = 1 if qtype == 1 and qclass == 1 else 0
        header = transaction_id + struct.pack("!HHHHH", response_flags, 1, answer_count, 0, 0)
        question = packet[12:question_end]
        if not answer_count:
            return header + question

        answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 5, 4) + socket.inet_aton(portal_ip)
        return header + question + answer

    def serve_forever(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_ip, self.port))
        sock.settimeout(0.5)
        self._sock = sock
        try:
            while not self._stop.is_set():
                try:
                    packet, address = sock.recvfrom(4096)
                except TimeoutError:
                    continue
                response = self.build_response(packet, self.portal_ip)
                if response:
                    sock.sendto(response, address)
        finally:
            sock.close()
            self._sock = None

    def stop(self) -> None:
        self._stop.set()
