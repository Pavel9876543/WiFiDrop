from __future__ import annotations

import os
import socket
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class MobileHotspotInfo:
    adapter_name: str
    description: str
    ipv4: str


def _is_private_ipv4(value: str) -> bool:
    try:
        packed = socket.inet_aton(value)
    except OSError:
        return False
    first, second, _, _ = packed
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168)


def _candidate_score(name: str, ipv4: str) -> tuple[int, int, str]:
    """Rank interfaces that are likely to be Windows Mobile Hotspot adapters."""
    lowered = name.casefold()
    score = 100
    if ipv4.startswith("192.168.137."):
        score -= 80
    if ipv4.endswith(".1"):
        score -= 10
    if any(token in lowered for token in ("local area connection*", "подключение по локальной сети*", "wi-fi direct", "mobile hotspot")):
        score -= 20
    if any(token in lowered for token in ("ethernet", "realtek", "tap", "vpn", "loopback")):
        score += 40
    return (score, len(name), name.casefold())


def detect_mobile_hotspot() -> MobileHotspotInfo | None:
    """Detect the private adapter used by Windows Mobile Hotspot.

    This intentionally uses psutil/Windows networking APIs directly. It avoids
    flashing console windows and preserves Unicode adapter
    names without parsing localized command output.
    """
    if os.name != "nt":
        return None

    stats = psutil.net_if_stats()
    candidates: list[MobileHotspotInfo] = []
    for name, addresses in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        for address in addresses:
            if address.family != socket.AF_INET:
                continue
            ipv4 = address.address
            if not _is_private_ipv4(ipv4) or ipv4.startswith("169.254."):
                continue
            candidates.append(MobileHotspotInfo(name, name, ipv4))

    if not candidates:
        return None
    candidates.sort(key=lambda item: _candidate_score(item.adapter_name, item.ipv4))
    best = candidates[0]
    # Avoid treating an ordinary LAN adapter as a hotspot unless it has a
    # gateway-like address or the conventional Windows ICS subnet.
    if not (best.ipv4.startswith("192.168.137.") or best.ipv4.endswith(".1")):
        return None
    return best


def open_mobile_hotspot_settings() -> None:
    if os.name == "nt":
        os.startfile("ms-settings:network-mobilehotspot")  # type: ignore[attr-defined]
