import socket


def get_local_ipv4_addresses() -> list[str]:
    """Return non-loopback IPv4 addresses without requiring internet access."""
    addresses: set[str] = set()
    try:
        host_info = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
        addresses.update(item[4][0] for item in host_info)
    except OSError:
        return []
    return sorted(address for address in addresses if not address.startswith("127."))


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
