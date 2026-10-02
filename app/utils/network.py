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


def get_router_interfaces() -> list[tuple[str, str]]:
    """Active IPv4 interfaces, with physical LAN adapters ranked before VPN/hotspot."""
    import ipaddress

    import psutil

    try:
        stats = psutil.net_if_stats()
        interface_addresses = psutil.net_if_addrs()
    except (OSError, psutil.Error):
        # Some restricted environments do not permit interface enumeration.
        return [("Локальный адаптер", ip) for ip in get_local_ipv4_addresses()]
    result = []
    for name, addresses in interface_addresses.items():
        if name in stats and not stats[name].isup:
            continue
        for item in addresses:
            if item.family != socket.AF_INET:
                continue
            ip = ipaddress.IPv4Address(item.address)
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
                continue
            result.append((name, str(ip)))

    def rank(item: tuple[str, str]) -> tuple[int, str, str]:
        name, ip = item
        virtual = any(
            token in name.casefold()
            for token in (
                "vpn",
                "tap",
                "tun",
                "tailscale",
                "docker",
                "vethernet",
                "virtual",
                "hotspot",
                "wi-fi direct",
                "local area connection*",
                "подключение по локальной сети*",
            )
        ) or ip.startswith("192.168.137.")
        return (int(virtual), name.casefold(), ip)

    return sorted(set(result), key=rank)


def select_router_ip(configured_ip: str | None, host: str = "0.0.0.0") -> str:
    interfaces = get_router_interfaces()
    candidates = [ip for _, ip in interfaces]
    if host != "0.0.0.0":
        if host not in candidates:
            raise ValueError("В режиме роутера HOST должен быть 0.0.0.0 или локальным IPv4")
        if configured_ip and configured_ip != host:
            raise ValueError("Выбранный IP не совпадает с адресом прослушивания HOST")
        return host
    if configured_ip:
        if configured_ip not in candidates:
            raise ValueError("Выбранный IP отсутствует на активных адаптерах этого компьютера")
        return configured_ip
    if not candidates:
        raise ValueError("Локальная сеть не найдена. Подключите компьютер к роутеру")
    return candidates[0]
