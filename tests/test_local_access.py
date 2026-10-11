"""Регрессии доступа по имени, выбора адаптера и правил брандмауэра."""

import subprocess
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.hotspot import windows
from app.services import router_access


def test_hotspot_name_uses_gui_adapter_without_captive(monkeypatch):
    settings = Settings(
        _env_file=None,
        local_domain="Отрожка",
        WIFIDROP_ACCESS_IP="192.168.137.1",
        captive_portal_enabled=False,
        router_ip="192.168.1.99",
    )
    selected = []
    monkeypatch.setattr(
        router_access, "select_router_ip", lambda ip, host: selected.append((ip, host)) or ip
    )
    monkeypatch.setattr(router_access, "detect_mobile_hotspot", Mock(side_effect=AssertionError))
    save = Mock()
    monkeypatch.setattr(router_access, "save_qr", save)
    access = router_access.RouterAccess(settings)
    announce = Mock()
    monkeypatch.setattr(access, "_announce", announce)
    payload = access.start()
    assert selected == [("192.168.137.1", "0.0.0.0")]
    announce.assert_called_once_with("xn--80almoaln.local", "192.168.137.1")
    assert payload["url"] == payload["ip_url"]  # До проверки домен не выбран для открытия.
    assert payload["domain_url"] == "http://xn--80almoaln.local:8000/"
    assert payload["ip_url"] == "http://192.168.137.1:8000/"
    save.assert_called_once_with(payload["ip_url"])


def test_cli_isolated_hotspot_uses_gateway(monkeypatch):
    settings = Settings(_env_file=None, hotspot_enabled=True, local_domain="otrozhka")
    monkeypatch.setattr(router_access, "select_router_ip", lambda ip, _: ip)
    monkeypatch.setattr(router_access, "save_qr", Mock())
    access = router_access.RouterAccess(settings)
    announce = Mock()
    monkeypatch.setattr(access, "_announce", announce)
    assert access.start()["ip_url"] == "http://192.168.50.1:8000/"
    announce.assert_called_once_with("otrozhka.local", "192.168.50.1")


def test_hotspot_lifespan_announces_and_releases_name(monkeypatch, tmp_path):
    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            _env_file=None,
            local_domain="otrozhka",
            upload_dir=tmp_path / "files",
            log_dir=tmp_path / "logs",
        ),
    )
    access = Mock()
    monkeypatch.setattr(main_module, "RouterAccess", lambda _: access)
    with TestClient(main_module.create_app()) as client:
        assert client.get("/").status_code == 200
        access.start.assert_called_once()
        access.close.assert_not_called()
    access.close.assert_called_once()


def test_router_firewall_opens_only_http_and_mdns(monkeypatch):
    commands = []

    def run(command, **_):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1 if "show" in command else 0, "", "")

    monkeypatch.setattr(windows, "_run", run)
    windows.ensure_firewall_rules(8123, access_only=True, mdns=True)
    added = [command for command in commands if "add" in command]
    assert len(added) == 2
    assert "protocol=TCP" in added[0] and "localport=8123" in added[0]
    assert "protocol=UDP" in added[1] and "localport=5353" in added[1]
    assert "remoteip=localsubnet" in added[1]
    assert not any(f"localport={port}" in c for c in added for port in (53, 67, 80))


def test_existing_http_rule_cannot_mask_missing_mdns_or_new_port(monkeypatch):
    names = {"WiFiDrop App 8000"}

    def run(command, **_):
        name = next(arg[5:] for arg in command if arg.startswith("name="))
        return subprocess.CompletedProcess(command, 0 if name in names else 1, name, "")

    monkeypatch.setattr(windows, "_run", run)
    assert windows.firewall_rules_present(8000, access_only=True)
    assert not windows.firewall_rules_present(8000, access_only=True, mdns=True)
    assert not windows.firewall_rules_present(8123, access_only=True)


def test_repeated_firewall_setup_does_not_add_duplicate_rules(monkeypatch):
    names = set()
    added = []

    def run(command, **_):
        name = next(arg[5:] for arg in command if arg.startswith("name="))
        if "show" in command:
            return subprocess.CompletedProcess(command, 0 if name in names else 1, name, "")
        names.add(name)
        added.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(windows, "_run", run)
    for _ in range(2):
        windows.ensure_firewall_rules(8000, access_only=True, mdns=True)
    assert len(added) == 2
