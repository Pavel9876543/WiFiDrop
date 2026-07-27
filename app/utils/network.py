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

