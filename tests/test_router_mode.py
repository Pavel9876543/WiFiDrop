from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.config.settings import Settings
from app.services import router_connection as router
from app.utils.local_name import local_hostname


@pytest.fixture
def local_network(monkeypatch):
    monkeypatch.setattr(router, "get_local_ipv4_addresses", lambda: ["192.168.1.42", "10.0.0.5"])
    monkeypatch.setattr(router, "get_preferred_local_ipv4_address", lambda: "192.168.1.42")


@pytest.mark.parametrize("name", ["otrozhka", "отрожка", "ОТРОЖКА.local", "xn--80almoaln"])
def test_local_name_accepts_unicode_and_ascii(name):
    settings = Settings(_env_file=None, local_name=name)
    assert settings.local_name
    assert local_hostname(settings.local_name).isascii()
    assert local_hostname(settings.local_name).endswith(".local")
    if "отрожка" in name.lower():
        assert settings.local_name == "отрожка"


@pytest.mark.parametrize(
    "name", ["http://otrozhka", "otrozhka:8000", "a.b", "bad name", "-abc", "123", "a" * 64]
)
def test_invalid_local_name_is_rejected(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, local_name=name)


def test_router_overrides_all_hotspot_flags():
    settings = Settings(
        _env_file=None,
        connection_mode="router",
        hotspot_enabled=True,
        captive_portal_enabled=True,
        auto_create_hotspot=True,
    )
    assert not settings.effective_hotspot_enabled
    assert not settings.effective_captive_enabled
    assert Settings(_env_file=None, hotspot_enabled=True).effective_hotspot_enabled


def test_router_probe_does_not_redirect(monkeypatch):
    from app.api.routes import captive_portal
    from app.main import create_app

    settings = Settings(_env_file=None, connection_mode="router", hotspot_enabled=True)
    monkeypatch.setattr(captive_portal, "get_settings", lambda: settings)
    monkeypatch.setattr("app.api.routes.pages.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        response = client.get("/generate_204", follow_redirects=False)
        assert response.status_code == 204
        assert "location" not in response.headers
        assert client.get("/.well-known/captive-portal").json() == {"captive": False}
        assert client.get("/").status_code == 200
        assert 'id="open-browser-button"' not in client.get("/?captive=1").text


def test_router_selects_interface_not_gateway(local_network):
    assert router.select_router_ip(Settings(_env_file=None)) == "192.168.1.42"
    assert router.select_router_ip(Settings(_env_file=None, router_ip="10.0.0.5")) == "10.0.0.5"
    with pytest.raises(ValueError):
        router.select_router_ip(Settings(_env_file=None, router_ip="192.168.1.1"))
    with pytest.raises(ValueError):
        router.select_router_ip(Settings(_env_file=None, host="127.0.0.1"))


def test_qr_saved_outside_cwd_and_replaced(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    path = router.save_url_qr("http://192.168.1.42:8000/", root=project)
    first = path.read_bytes()
    assert path == project / router.QR_FILENAME
    assert not (tmp_path / router.QR_FILENAME).exists()
    assert Image.open(path).format == "PNG"
    router.save_url_qr("http://otrozhka.local:8000/", root=project)
    assert path.read_bytes() != first
    assert not list(project.glob(".wifidrop-qr-*"))


def test_name_used_in_qr_and_closed(local_network, monkeypatch):
    publisher = Mock(hostname="xn--80almoaln.local")
    monkeypatch.setattr(router, "LocalNamePublisher", Mock(return_value=publisher))
    qr = Mock(return_value=Path("WiFiDrop_QR.png"))
    monkeypatch.setattr(router, "save_url_qr", qr)
    connection = router.RouterConnection(Settings(_env_file=None, local_name="отрожка"), Mock())
    connection.start()
    assert connection.ip_url == "http://192.168.1.42:8000/"
    assert connection.display_url == "http://отрожка.local:8000/"
    qr.assert_called_once_with("http://xn--80almoaln.local:8000/")
    connection.close()
    connection.close()
    publisher.close.assert_called_once()


def test_name_conflict_falls_back_to_ip(local_network, monkeypatch):
    publisher = Mock()
    publisher.start.side_effect = ValueError("Имя занято")
    monkeypatch.setattr(router, "LocalNamePublisher", Mock(return_value=publisher))
    qr = Mock(return_value=Path("WiFiDrop_QR.png"))
    monkeypatch.setattr(router, "save_url_qr", qr)
    connection = router.RouterConnection(Settings(_env_file=None, local_name="otrozhka"), Mock())
    connection.start()
    qr.assert_called_once_with("http://192.168.1.42:8000/")
    assert connection.publisher is None


def test_mdns_unregistered_on_stop(monkeypatch):
    zc = Mock()
    zc.cache.entries_with_name.return_value = []
    monkeypatch.setattr(router, "Zeroconf", Mock(return_value=zc))
    monkeypatch.setattr(router.time, "sleep", lambda _: None)
    publisher = router.LocalNamePublisher("отрожка", "192.168.1.42", 8000)
    publisher.start()
    assert publisher.info.server == local_hostname("отрожка") + "."
    assert publisher.info.parsed_addresses() == ["192.168.1.42"]
    assert publisher.info.port == 8000
    info = publisher.info
    publisher.close()
    zc.unregister_service.assert_called_once_with(info)
    zc.close.assert_called_once()


def test_mdns_host_conflict_closes_socket(monkeypatch):
    import socket
    import time

    from zeroconf import DNSAddress

    zc = Mock()
    record = DNSAddress(
        "otrozhka.local.",
        1,
        1,
        120,
        socket.inet_aton("192.168.1.99"),
        created=time.monotonic() * 1000,
    )
    zc.cache.entries_with_name.return_value = [record]
    monkeypatch.setattr(router, "Zeroconf", Mock(return_value=zc))
    monkeypatch.setattr(router.time, "sleep", lambda _: None)
    publisher = router.LocalNamePublisher("otrozhka", "192.168.1.42", 8000)
    with pytest.raises(ValueError, match="уже используется"):
        publisher.start()
    zc.register_service.assert_not_called()
    zc.close.assert_called_once()


def test_console_router_never_starts_hotspot_or_captive(local_network, monkeypatch):
    import start

    settings = Settings(
        _env_file=None, connection_mode="router", hotspot_enabled=True, captive_portal_enabled=True
    )
    monkeypatch.setattr(start, "get_settings", lambda: settings)
    monkeypatch.delenv("WIFIDROP_GUI_ROUTER", raising=False)
    hotspot = Mock(side_effect=AssertionError("hotspot must not run"))
    captive = Mock(side_effect=AssertionError("captive must not run"))
    monkeypatch.setattr(start, "WindowsCaptiveHotspot", hotspot)
    monkeypatch.setattr(start, "_run_captive_listener", captive)
    connection = Mock()
    monkeypatch.setattr(start, "RouterConnection", Mock(return_value=connection))
    monkeypatch.setattr(start.uvicorn, "run", Mock())
    start.main()
    connection.start.assert_called_once()
    connection.close.assert_called_once()
    hotspot.assert_not_called()
    captive.assert_not_called()


@pytest.mark.parametrize(
    "resolved,expected",
    [("192.168.1.42", "http://otrozhka:8000/"), ("192.168.1.99", "http://192.168.1.42:8000/")],
)
def test_router_dns_name_requires_correct_mapping(local_network, monkeypatch, resolved, expected):
    import socket

    monkeypatch.setattr(
        router.socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, 0))],
    )
    publisher = Mock(side_effect=AssertionError("DNS mode must not publish mDNS"))
    monkeypatch.setattr(router, "LocalNamePublisher", publisher)
    qr = Mock(return_value=Path("WiFiDrop_QR.png"))
    monkeypatch.setattr(router, "save_url_qr", qr)
    settings = Settings(_env_file=None, local_name="otrozhka", local_name_mode="dns")
    connection = router.RouterConnection(settings, Mock())
    connection.start()
    qr.assert_called_once_with(expected)
    publisher.assert_not_called()


def test_dns_mode_accepts_full_cyrillic_domain():
    settings = Settings(_env_file=None, local_name="Отрожка.home.arpa", local_name_mode="dns")
    assert settings.local_name == "отрожка.home.arpa"
    assert local_hostname(settings.local_name, "dns").startswith("xn--")
    assert local_hostname(settings.local_name, "dns").endswith(".home.arpa")
