from __future__ import annotations

import json
import socket
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class MobileHotspotInfo:
    adapter_name: str
    description: str
    ipv4: str


def _run_powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        check=check,
        encoding="utf-8",
        errors="replace",
    )


def _is_private_ipv4(value: str) -> bool:
    try:
        packed = socket.inet_aton(value)
    except OSError:
        return False
    first, second, _, _ = packed
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168)


def detect_mobile_hotspot() -> MobileHotspotInfo | None:
    """Detect the private adapter created by Windows Mobile Hotspot.

    Windows normally exposes it as a Microsoft Wi-Fi Direct Virtual Adapter.
    The address is intentionally discovered instead of assuming 192.168.137.1.
    """
    script = r'''
$items = Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Up' -and ($_.InterfaceDescription -match 'Wi-Fi Direct|Mobile Hotspot') } |
    ForEach-Object {
        $a = $_
        Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '169.254.*' } |
            ForEach-Object {
                [PSCustomObject]@{ Name=$a.Name; Description=$a.InterfaceDescription; IPv4=$_.IPAddress }
            }
    }
$items | ConvertTo-Json -Compress
'''
    try:
        result = _run_powershell(script, check=False)
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    candidates = [item for item in data if isinstance(item, dict) and _is_private_ipv4(str(item.get("IPv4", "")))]
    if not candidates:
        return None
    # Prefer the conventional ICS subnet when several Wi-Fi Direct interfaces exist.
    candidates.sort(key=lambda item: 0 if str(item.get("IPv4", "")).startswith("192.168.137.") else 1)
    item = candidates[0]
    return MobileHotspotInfo(
        adapter_name=str(item.get("Name", "")),
        description=str(item.get("Description", "")),
        ipv4=str(item.get("IPv4", "")),
    )


def open_mobile_hotspot_settings() -> None:
    # Launch and return immediately so opening Settings can never block the Qt UI.
    subprocess.Popen(
        ["cmd.exe", "/c", "start", "", "ms-settings:network-mobilehotspot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
