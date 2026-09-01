from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import psutil


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


def _hidden_process_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=check,
        encoding="utf-8",
        errors="replace",
        **_hidden_process_kwargs(),
    )


def hosted_network_supported() -> bool:
    result = _run(["netsh", "wlan", "set", "hostednetwork", "mode=allow"], check=False)
    return result.returncode == 0


def _find_hosted_adapter() -> HotspotAdapter | None:
    stats = psutil.net_if_stats()
    candidates: list[str] = []
    for name, addresses in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        lowered = name.casefold()
        if any(token in lowered for token in ("local area connection*", "подключение по локальной сети*", "wi-fi direct", "hosted", "virtual")):
            candidates.append(name)
    if not candidates:
        return None
    candidates.sort()
    return HotspotAdapter(candidates[0], candidates[0])


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

    adapter = _find_hosted_adapter()
    if adapter is None:
        stop_hosted_network()
        raise HotspotError("Hosted network started, but its virtual adapter could not be identified")
    return adapter


def configure_adapter(adapter_name: str, gateway_ip: str) -> None:
    result = _run(
        [
            "netsh", "interface", "ipv4", "set", "address",
            f"name={adapter_name}", "source=static", f"address={gateway_ip}", "mask=255.255.255.0", "gateway=none",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise HotspotError(result.stderr.strip() or result.stdout.strip() or "Unable to configure hotspot adapter")


_FIREWALL_RULES = (
    ("TCP", "{app_port}", "WiFiDrop App"),
    ("TCP", "80", "WiFiDrop Captive HTTP"),
    ("UDP", "53", "WiFiDrop Captive DNS"),
    ("UDP", "67", "WiFiDrop DHCP"),
)


def firewall_rules_present(app_port: int) -> bool:
    for _protocol, _port, name in _FIREWALL_RULES:
        result = _run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"], check=False)
        if result.returncode != 0:
            return False
        text = (result.stdout + result.stderr).casefold()
        if name.casefold() not in text:
            return False
    return True


def ensure_firewall_rules(app_port: int) -> None:
    for protocol, raw_port, name in _FIREWALL_RULES:
        port = raw_port.format(app_port=app_port)
        result = _run([
            "netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", "action=allow",
            f"protocol={protocol}", f"localport={port}", "profile=private,public"
        ], check=False)
        if result.returncode != 0:
            raise PermissionError(result.stderr.strip() or result.stdout.strip() or f"Unable to add firewall rule: {name}")


def _pythonw_executable() -> str:
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else executable)


def ensure_firewall_rules_with_elevation(app_port: int, timeout: float = 30.0) -> bool:
    """Ensure firewall rules, requesting UAC only when the rules are absent."""
    if os.name != "nt" or firewall_rules_present(app_port):
        return True
    if is_windows_admin():
        ensure_firewall_rules(app_port)
        return firewall_rules_present(app_port)

    marker = Path(tempfile.gettempdir()) / f"wifidrop_firewall_{os.getpid()}_{int(time.time() * 1000)}.txt"
    params = f'-X utf8 -m app.firewall_helper --port {int(app_port)} --marker "{marker}"'
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        _pythonw_executable(),
        params,
        str(Path(__file__).resolve().parents[2]),
        0,
    )
    if int(result) <= 32:
        return False

    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if marker.exists():
                return marker.read_text(encoding="utf-8", errors="replace").strip() == "ok"
            time.sleep(0.15)
        return firewall_rules_present(app_port)
    finally:
        marker.unlink(missing_ok=True)


def stop_hosted_network() -> None:
    _run(["netsh", "wlan", "stop", "hostednetwork"], check=False)


def open_mobile_hotspot_settings() -> None:
    if os.name == "nt":
        os.startfile("ms-settings:network-mobilehotspot")  # type: ignore[attr-defined]
