from __future__ import annotations

import ctypes
import json
import subprocess
from dataclasses import dataclass


class HotspotError(RuntimeError):
    pass


@dataclass(frozen=True)
class HotspotAdapter:
    name: str
    description: str


def is_windows_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check, encoding="utf-8", errors="replace")


def _powershell(script: str) -> str:
    result = _run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
    return result.stdout.strip()


def hosted_network_supported() -> bool:
    # `netsh ... set hostednetwork` succeeds only when the installed driver exposes
    # the legacy Hosted Network backend. This is more robust than parsing localized
    # `netsh wlan show drivers` output.
    result = _run(["netsh", "wlan", "set", "hostednetwork", "mode=allow"], check=False)
    return result.returncode == 0


def configure_and_start_hosted_network(ssid: str, password: str) -> HotspotAdapter:
    if len(password) < 8 or len(password) > 63:
        raise HotspotError("HOTSPOT_PASSWORD must contain 8-63 characters")
    if not hosted_network_supported():
        raise HotspotError(
            "The Wi-Fi driver does not support Windows Hosted Network. "
            "A full WiFiDrop captive hotspot cannot be created with this adapter."
        )
    configure = _run(
        ["netsh", "wlan", "set", "hostednetwork", "mode=allow", f"ssid={ssid}", f"key={password}", "keyUsage=persistent"],
        check=False,
    )
    if configure.returncode != 0:
        raise HotspotError(configure.stderr.strip() or configure.stdout.strip() or "Unable to configure hosted network")
    start = _run(["netsh", "wlan", "start", "hostednetwork"], check=False)
    if start.returncode != 0:
        raise HotspotError(start.stderr.strip() or start.stdout.strip() or "Unable to start hosted network")

    raw = _powershell(
        "$a=Get-NetAdapter -IncludeHidden | Where-Object { $_.Status -eq 'Up' -and "
        "($_.InterfaceDescription -match 'Hosted|Virtual|Wi-Fi Direct') } | "
        "Select-Object -First 1 Name,InterfaceDescription; $a | ConvertTo-Json -Compress"
    )
    if not raw:
        stop_hosted_network()
        raise HotspotError("Hosted network started, but its virtual adapter could not be identified")
    data = json.loads(raw)
    return HotspotAdapter(name=data["Name"], description=data.get("InterfaceDescription", ""))


def configure_adapter(adapter_name: str, gateway_ip: str) -> None:
    escaped = adapter_name.replace("'", "''")
    _powershell(
        f"$n='{escaped}'; Set-NetIPInterface -InterfaceAlias $n -Dhcp Disabled -ErrorAction SilentlyContinue; "
        f"Get-NetIPAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue; "
        f"New-NetIPAddress -InterfaceAlias $n -IPAddress '{gateway_ip}' -PrefixLength 24 -AddressFamily IPv4 -ErrorAction Stop | Out-Null"
    )


def ensure_firewall_rules(app_port: int) -> None:
    ports = [("TCP", app_port, "WiFiDrop App"), ("TCP", 80, "WiFiDrop Captive HTTP"), ("UDP", 53, "WiFiDrop Captive DNS"), ("UDP", 67, "WiFiDrop DHCP")]
    for protocol, port, name in ports:
        _run([
            "netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", "action=allow",
            f"protocol={protocol}", f"localport={port}", "profile=private,public"
        ], check=False)


def stop_hosted_network() -> None:
    _run(["netsh", "wlan", "stop", "hostednetwork"], check=False)


def open_mobile_hotspot_settings() -> None:
    _run(["cmd", "/c", "start", "", "ms-settings:network-mobilehotspot"], check=False)
