import socket
import struct

from app.hotspot.dhcp import ACK, DHCP_MAGIC, OFFER, CaptiveDhcpServer
from app.hotspot.dns import CaptiveDnsServer


def _dns_query(name: str) -> bytes:
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split(".")) + b"\x00"
    return b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + labels + struct.pack("!HH", 1, 1)


def _dhcp_packet(message_type: int) -> bytes:
    packet = bytearray(236)
    packet[0] = 1
    packet[1] = 1
    packet[2] = 6
    packet[4:8] = b"\x01\x02\x03\x04"
    packet[28:34] = b"\xaa\xbb\xcc\xdd\xee\xff"
    return bytes(packet) + DHCP_MAGIC + bytes([53, 1, message_type, 255])


def test_captive_dns_resolves_every_a_query_to_portal() -> None:
    response = CaptiveDnsServer.build_response(_dns_query("connectivitycheck.gstatic.com"), "192.168.50.1")
    assert response is not None
    assert response[:2] == b"\x12\x34"
    assert response[-4:] == socket.inet_aton("192.168.50.1")


def test_dhcp_offer_and_ack_announce_gateway_dns_and_option_114() -> None:
    server = CaptiveDhcpServer("192.168.50.1", "192.168.50.1")
    offer = server.build_response(_dhcp_packet(1))
    ack = server.build_response(_dhcp_packet(3))
    assert offer is not None and ack is not None
    assert bytes([53, 1, OFFER]) in offer
    assert bytes([53, 1, ACK]) in ack
    assert bytes([6, 4]) + socket.inet_aton("192.168.50.1") in offer
    assert bytes([114]) in offer
    assert b"/.well-known/captive-portal" in offer


def test_dhcp_without_captive_portal_does_not_announce_dns_or_option_114() -> None:
    server = CaptiveDhcpServer(
        "192.168.50.1",
        "192.168.50.1",
        captive_portal_enabled=False,
    )
    offer = server.build_response(_dhcp_packet(1))

    assert offer is not None
    assert bytes([53, 1, OFFER]) in offer
    assert bytes([6, 4]) + socket.inet_aton("192.168.50.1") not in offer
    assert bytes([114]) not in offer
    assert b"/.well-known/captive-portal" not in offer
