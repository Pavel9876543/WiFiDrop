import socket
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import start
from app.api.routes import captive_portal
from app.config.settings import Settings
from app.services import router_access
from app.utils import network
from app.utils.local_name import domain_hostname


def router_settings(**kwargs):
    return Settings(_env_file=None, connection_mode="router", **kwargs)


@pytest.mark.parametrize(
    ("name", "host"),
    [
        ("otrozhka", "otrozhka.local"),
        ("Отрожка", "xn--80almoaln.local"),
        ("otrozhka.local", "otrozhka.local"),
    ],
)
def test_local_names_and_idna(name, host):
    settings = router_settings(local_domain=name)
    assert domain_hostname(settings.local_domain, "mdns") == host


@pytest.mark.parametrize(
    "name",
    [
        "http://otrozhka",
        "name:8000",
        "bad name",
        "a..b",
        "-name",
        "127.0.0.1",
        "a" * 64,
        "x.example.org",
    ],
)
def test_invalid_mdns_name_rejected(name):
    with pytest.raises(ValidationError):
        router_settings(local_domain=name)


def test_router_dns_accepts_single_word_and_unicode():
    settings = router_settings(local_domain="Отрожка", local_domain_method="router_dns")
    assert domain_hostname(settings.local_domain, settings.local_domain_method) == "xn--80almoaln"
    with pytest.raises(ValidationError):
        router_settings(local_domain="name.local", local_domain_method="router_dns")


@pytest.mark.parametrize("hotspot", [False, True])
def test_router_mode_overrides_captive_flags(monkeypatch, hotspot):
    settings = router_settings(hotspot_enabled=hotspot, captive_portal_enabled=True)
    monkeypatch.setattr(captive_portal, "get_settings", lambda: settings)
    assert not settings.captive_enabled
    from app.main import create_app

    client = TestClient(create_app())
    assert client.get("/generate_204").status_code == 204
    assert client.get("/.well-known/captive-portal").json() == {"captive": False}
    assert client.get("/captive-portal").status_code == 404


def test_cli_router_does_not_start_hotspot_or_captive_listener(monkeypatch):
    settings = router_settings(hotspot_enabled=True)
    monkeypatch.setattr(start, "get_settings", lambda: settings)
    forbidden = Mock(side_effect=AssertionError("hotspot called in router mode"))
    monkeypatch.setattr(start, "WindowsCaptiveHotspot", forbidden)
    monkeypatch.setattr(start, "_run_captive_listener", forbidden)
    run = Mock()
    monkeypatch.setattr(start.uvicorn, "Server", lambda *_: Mock(run=run))
    start.main()
    forbidden.assert_not_called()
    run.assert_called_once()
    assert settings.port == 8000


def test_select_local_ip_respects_listener_and_missing_address(monkeypatch):
    monkeypatch.setattr(network, "get_router_interfaces", lambda: [("Wi-Fi", "192.168.1.20")])
    assert network.select_router_ip(None) == "192.168.1.20"
    assert network.select_router_ip("192.168.1.20") == "192.168.1.20"
    for ip, host in [
        ("192.168.1.21", "0.0.0.0"),
        (None, "127.0.0.1"),
        ("192.168.1.21", "192.168.1.20"),
    ]:
        with pytest.raises(ValueError):
            network.select_router_ip(ip, host)


def test_physical_interface_preferred_to_vpn(monkeypatch):
    from types import SimpleNamespace

    import psutil

    def address(ip):
        return SimpleNamespace(family=socket.AF_INET, address=ip)

    monkeypatch.setattr(
        psutil,
        "net_if_stats",
        lambda: {
            "Wi-Fi": SimpleNamespace(isup=True),
            "Offline": SimpleNamespace(isup=False),
        },
    )
    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {
            "SocksTunnel": [address("10.6.7.2")],
            "Wi-Fi": [address("192.168.1.20")],
            "Offline": [address("192.168.2.20")],
            "Loopback": [address("127.0.0.1")],
        },
    )
    assert network.get_router_interfaces() == [
        ("Wi-Fi", "192.168.1.20"),
        ("SocksTunnel", "10.6.7.2"),
    ]


@pytest.fixture
def access_environment(monkeypatch, tmp_path):
    path = tmp_path / "wifidrop_qr.png"
    monkeypatch.setattr(router_access, "QR_PATH", path)
    monkeypatch.setattr(router_access, "select_router_ip", lambda *_: "192.168.1.20")
    saved = []
    monkeypatch.setattr(router_access, "save_qr", lambda url: saved.append(url))
    return path, saved


def test_qr_uses_ip_without_name(access_environment):
    path, saved = access_environment
    payload = router_access.RouterAccess(router_settings(port=8123)).start()
    assert payload == {
        "ip_url": "http://192.168.1.20:8123/",
        "domain_url": "",
        "url": saved[0],
        "qr_path": str(path),
    }
    assert saved == ["http://192.168.1.20:8123/"]


def test_qr_uses_advertised_name_and_cleanup(monkeypatch, access_environment):
    instances = []

    class FakeZeroconf:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.registered = None
            self.closed = False
            self.unregistered = None
            instances.append(self)

        def register_service(self, info, **kwargs):
            assert kwargs == {"allow_name_change": False}
            self.registered = info

        def unregister_service(self, info):
            self.unregistered = info

        def close(self):
            self.closed = True

    resolver = Mock()
    resolver.parsed_addresses.return_value = []
    monkeypatch.setattr(router_access, "AddressResolverIPv4", lambda *_: resolver)
    monkeypatch.setattr(router_access, "Zeroconf", FakeZeroconf)
    access = router_access.RouterAccess(router_settings(local_domain="Отрожка"))
    payload = access.start()
    assert payload["url"] == "http://xn--80almoaln.local:8000/"
    assert access_environment[1] == [payload["url"]]
    assert instances[0].kwargs["interfaces"] == ["192.168.1.20"]
    assert instances[0].registered.server == "xn--80almoaln.local."
    access.close()
    access.close()
    assert instances[0].closed
    assert instances[0].unregistered is instances[0].registered


def test_name_failure_falls_back_to_ip(monkeypatch, access_environment):
    access = router_access.RouterAccess(router_settings(local_domain="otrozhka"))
    monkeypatch.setattr(access, "_announce", Mock(side_effect=ValueError("conflict")))
    payload = access.start()
    assert payload["domain_url"] == ""
    assert payload["url"] == "http://192.168.1.20:8000/"


@pytest.mark.parametrize("ip", ["192.168.1.20", "192.168.1.99"])
def test_router_dns_name_is_verified(monkeypatch, access_environment, ip):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *_args, **_kwargs: [(socket.AF_INET, 1, 6, "", (ip, 0))]
    )
    payload = router_access.RouterAccess(
        router_settings(
            local_domain="otrozhka",
            local_domain_method="router_dns",
        )
    ).start()
    expected = "http://otrozhka:8000/" if ip.endswith(".20") else "http://192.168.1.20:8000/"
    assert payload["url"] == expected


def test_qr_failure_does_not_advertise_previous_image(monkeypatch, access_environment):
    path, _ = access_environment
    path.write_bytes(b"old QR")
    monkeypatch.setattr(router_access, "save_qr", Mock(side_effect=OSError("read only")))
    payload = router_access.RouterAccess(router_settings()).start()
    assert payload["qr_path"] == ""
    assert not path.exists()


def test_save_qr_is_png_and_preserves_previous_file_on_failure(monkeypatch, tmp_path):
    from PIL import Image

    path = tmp_path / "wifidrop_qr.png"
    router_access.save_qr("http://192.168.1.20:8000/", path)
    with Image.open(path) as image:
        assert image.format == "PNG"
    old = path.read_bytes()
    monkeypatch.setattr(router_access.qrcode, "make", Mock(side_effect=OSError("failed")))
    with pytest.raises(OSError):
        router_access.save_qr("http://otrozhka.local:8000/", path)
    assert path.read_bytes() == old
    assert list(tmp_path.iterdir()) == [path]


def test_lifespan_releases_name_even_when_start_fails(monkeypatch, tmp_path):
    import app.main as main_module

    settings = router_settings(upload_dir=tmp_path / "files", log_dir=tmp_path / "logs")
    monkeypatch.setattr(main_module, "settings", settings)
    access = Mock()
    access.start.side_effect = ValueError("bad network")
    monkeypatch.setattr(main_module, "RouterAccess", lambda _: access)
    with pytest.raises(ValueError), TestClient(main_module.create_app()):
        pass
    access.close.assert_called_once()


def test_interface_enumeration_error_has_offline_fallback(monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "net_if_stats", Mock(side_effect=PermissionError("restricted")))
    monkeypatch.setattr(network, "get_local_ipv4_addresses", lambda: ["192.168.1.20"])
    assert network.select_router_ip(None) == "192.168.1.20"


def test_foreign_host_record_is_not_overwritten(monkeypatch, access_environment):
    zc = Mock()
    resolver = Mock()
    resolver.parsed_addresses.return_value = ["192.168.1.99"]
    monkeypatch.setattr(router_access, "Zeroconf", lambda **_: zc)
    monkeypatch.setattr(router_access, "AddressResolverIPv4", lambda *_: resolver)
    access = router_access.RouterAccess(router_settings(local_domain="otrozhka"))
    payload = access.start()
    assert not payload["domain_url"]
    zc.register_service.assert_not_called()
    zc.close.assert_called_once()
