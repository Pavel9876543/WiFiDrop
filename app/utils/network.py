import socket
from ipaddress import IPv4Address

import psutil


def get_local_ipv4_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses without requiring internet access."""
    addresses: set[str] = set()
    # hostname resolution on Windows may omit Ethernet/Wi-Fi when VPN or
    # virtual interfaces are also present. Enumerate active interfaces too.
    try:
        stats = psutil.net_if_stats()
        for name, entries in psutil.net_if_addrs().items():
            if name in stats and not stats[name].isup:
                continue
            addresses.update(item.address for item in entries if item.family == socket.AF_INET)
    except OSError:
        pass
    try:
        host_info = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
        addresses.update(item[4][0] for item in host_info)
    except OSError:
        pass
    return sorted(
        address
        for address in addresses
        if not (
            IPv4Address(address).is_loopback
            or IPv4Address(address).is_unspecified
            or IPv4Address(address).is_multicast
        )
    )


def get_preferred_local_ipv4_address() -> str | None:
    """Return the IPv4 address normally used for outbound LAN traffic.

    UDP connect does not send application data; it asks the OS which local address
    would be used for the route. If routing is unavailable, fall back to the first
    discovered non-loopback address.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()

    addresses = get_local_ipv4_addresses()
    return addresses[0] if addresses else None
