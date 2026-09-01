from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config.settings import get_settings
from app.utils.network import get_preferred_local_ipv4_address

router = APIRouter(include_in_schema=False)


def _portal_url(request: Request) -> str:
    settings = get_settings()
    if settings.captive_portal_public_url:
        return settings.captive_portal_public_url.rstrip("/") + "/"
    if settings.hotspot_enabled:
        return f"http://{settings.hotspot_gateway_ip}:{settings.port}/"

    address = get_preferred_local_ipv4_address()
    if address:
        return f"http://{address}:{settings.port}/"

    # Fallback is primarily useful when the captive listener shares the main port.
    hostname = request.url.hostname or "localhost"
    return f"http://{hostname}:{settings.port}/"


def _portal_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(_portal_url(request), status_code=302, headers={"Cache-Control": "no-store"})


# Android / ChromeOS connectivity probes. A normal unrestricted network returns 204;
# a redirect tells the OS that a sign-in page is present.
@router.get("/generate_204")
@router.get("/gen_204")
async def android_probe(request: Request) -> RedirectResponse:
    return _portal_redirect(request)


# Apple CNA (Captive Network Assistant). The success response normally contains the
# word "Success"; redirecting instead makes the portal page available to CNA.
@router.get("/hotspot-detect.html")
@router.get("/library/test/success.html")
async def apple_probe(request: Request) -> RedirectResponse:
    return _portal_redirect(request)


# Windows NCSI / Network Connectivity Status Indicator probes.
@router.get("/connecttest.txt")
@router.get("/ncsi.txt")
async def windows_probe(request: Request) -> RedirectResponse:
    return _portal_redirect(request)


@router.get("/redirect")
async def generic_probe(request: Request) -> RedirectResponse:
    return _portal_redirect(request)


@router.get("/.well-known/captive-portal")
async def captive_portal_api(request: Request) -> JSONResponse:
    """RFC 8908-style Captive Portal API response.

    Discovery of this URL still has to be announced by the network (for example
    with DHCP option 114 / RFC 8910). Merely serving the endpoint cannot make a
    client discover it on an arbitrary third-party router.
    """
    return JSONResponse(
        {
            "captive": True,
            "user-portal-url": _portal_url(request),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/captive-portal")
async def captive_portal_landing(request: Request) -> HTMLResponse:
    target = _portal_url(request)
    safe_target = target.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='refresh' content='0;url=" + safe_target + "'>"
        "<title>WiFiDrop</title></head><body>"
        "<p>Открываем WiFiDrop…</p>"
        f"<p><a href=\"{safe_target}\">Открыть WiFiDrop</a></p>"
        "</body></html>",
        headers={"Cache-Control": "no-store"},
    )
