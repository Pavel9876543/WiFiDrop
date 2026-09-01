from __future__ import annotations

import threading

import uvicorn

from app.config.settings import get_settings
from app.hotspot.manager import WindowsCaptiveHotspot
from app.hotspot.windows import HotspotError
from app.utils.network import get_local_ipv4_addresses, get_preferred_local_ipv4_address


def _run_captive_listener(host: str, port: int, log_level: str) -> None:
    uvicorn.run(
        "app.captive:app",
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
        workers=1,
    )


def main() -> None:
    settings = get_settings()
    hotspot: WindowsCaptiveHotspot | None = None

    if settings.hotspot_enabled:
        hotspot = WindowsCaptiveHotspot(
            ssid=settings.hotspot_ssid,
            password=settings.hotspot_password,
            gateway_ip=settings.hotspot_gateway_ip,
            app_port=settings.port,
        )
        print("\n[WiFiDrop] Creating an isolated captive Wi-Fi hotspot...")
        try:
            info = hotspot.start()
        except HotspotError as exc:
            print(f"[WiFiDrop] Hotspot could not be started: {exc}")
            print("[WiFiDrop] Opening Windows Mobile Hotspot settings as a fallback.")
            WindowsCaptiveHotspot.open_windows_fallback()
            print(
                "[WiFiDrop] Important: standard Windows Mobile Hotspot does not expose enough "
                "DHCP/DNS control to guarantee the system captive-portal notification."
            )
            return
        except OSError as exc:
            print(f"[WiFiDrop] DHCP/DNS could not bind to a required port: {exc}")
            print("[WiFiDrop] Check that UDP ports 53 and 67 and TCP port 80 are free, then retry as Administrator.")
            if hotspot:
                hotspot.stop()
            return
        print(f"[WiFiDrop] Hotspot SSID: {info.ssid}")
        print(f"[WiFiDrop] Hotspot password: {info.password}")
        print(f"[WiFiDrop] Portal: http://{info.gateway_ip}:{settings.port}/")
        print("[WiFiDrop] Connect a phone to this Wi-Fi and use the system 'Sign in to network' notification.")

    print(f"\n{settings.app_name} is ready:")
    print(f"  This computer: http://localhost:{settings.port}")
    for address in get_local_ipv4_addresses():
        print(f"  Local network: http://{address}:{settings.port}")

    captive_enabled = settings.captive_portal_enabled or settings.hotspot_enabled
    if captive_enabled:
        if settings.hotspot_enabled:
            portal_address = f"http://{settings.hotspot_gateway_ip}:{settings.port}/"
        else:
            portal_address = settings.captive_portal_public_url
            if not portal_address:
                preferred = get_preferred_local_ipv4_address()
                portal_address = f"http://{preferred}:{settings.port}/" if preferred else "automatic LAN address"
        if settings.captive_portal_port == settings.port:
            print(f"  Captive Portal probes: enabled on main port {settings.port}")
        else:
            print(f"  Captive Portal probes: http://0.0.0.0:{settings.captive_portal_port} -> {portal_address}")
            thread = threading.Thread(
                target=_run_captive_listener,
                args=(settings.host, settings.captive_portal_port, settings.log_level.lower()),
                name="wifidrop-captive-portal",
                daemon=True,
            )
            thread.start()

    print("\nPress Ctrl+C to stop the server.\n")
    try:
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            access_log=False,
            workers=1,
        )
    finally:
        if hotspot:
            print("[WiFiDrop] Stopping hotspot...")
            hotspot.stop()


if __name__ == "__main__":
    main()
