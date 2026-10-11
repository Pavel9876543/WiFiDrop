import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from app import gui
from app.config.settings import Settings


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(monkeypatch, qt_app):
    monkeypatch.setattr(
        gui,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            connection_mode="router",
            router_ip="192.168.1.20",
            captive_portal_enabled=True,
            hotspot_enabled=True,
        ),
    )
    # Keep network workers deterministic; no system network operations in a GUI unit test.
    monkeypatch.setattr(gui.WiFiDropWindow, "_start_worker", lambda *_args, **_kwargs: None)
    instance = gui.WiFiDropWindow()
    instance.timer.stop()
    yield instance
    instance.close()


def test_router_refresh_and_start_skip_hotspot(monkeypatch, window):
    forbidden = Mock(side_effect=AssertionError("hotspot operation"))
    for name in (
        "detect_mobile_hotspot",
        "ensure_hosted_network_with_elevation",
        "ensure_firewall_rules_with_elevation",
        "open_mobile_hotspot_settings",
        "CaptiveDnsServer",
        "CaptiveDhcpServer",
    ):
        monkeypatch.setattr(gui, name, forbidden)
    monkeypatch.setattr(gui, "get_router_interfaces", lambda: [("Wi-Fi", "192.168.1.20")])
    monkeypatch.setattr(gui, "select_router_ip", lambda *_: "192.168.1.20")
    monkeypatch.setattr(window, "_tcp_port_available", lambda *_: True)
    monkeypatch.setattr(window, "_start_worker", lambda function, success, *_: success(function()))
    launch = Mock()
    monkeypatch.setattr(window.process, "start", launch)
    window.refresh_network_state()
    window.start_server()
    forbidden.assert_not_called()
    launch.assert_called_once()
    env = window.process.processEnvironment()
    assert env.value("CONNECTION_MODE") == "router"
    assert env.value("CAPTIVE_PORTAL_ENABLED") == "false"
    assert env.value("HOTSPOT_ENABLED") == "false"
    assert env.value("WIFIDROP_GUI_CONTROL") == "1"
    assert env.value("ROUTER_IP") == "192.168.1.20"
    assert not window.settings_button.isEnabled()


def test_router_stop_uses_private_control_pipe(monkeypatch, window):
    monkeypatch.setattr(window, "process_is_running", lambda: True)
    write = Mock()
    terminate = Mock()
    monkeypatch.setattr(window.process, "write", write)
    monkeypatch.setattr(window.process, "terminate", terminate)
    window.stop_server()
    write.assert_called_once_with(b"stop\n")
    terminate.assert_not_called()
    monkeypatch.setattr(window, "process_is_running", lambda: False)


def test_split_output_line_renders_qr(monkeypatch, window, tmp_path):
    import json

    from app.services.router_access import save_qr

    url = "http://otrozhka.local:8000/"
    ip_url = "http://192.168.1.20:8000/"
    path = tmp_path / "qr.png"
    save_qr(ip_url, path)
    payload = {
        "ip_url": ip_url,
        "domain_url": url,
        "url": url,
        "qr_path": str(path),
    }
    line = (gui.ACCESS_PREFIX + json.dumps(payload) + "\n").encode()
    chunks = iter([line[:20], line[20:]])
    monkeypatch.setattr(window.process, "readAllStandardOutput", lambda: next(chunks))
    window._read_output()
    assert window.current_url is None
    window._read_output()
    assert window.current_url == url
    assert window.site_status.text() == payload["ip_url"]
    assert window.domain_status.text() == url
    assert not window.qr_image.pixmap().isNull()
    assert str(path) in window.qr_description.text()
    assert window.qr_description.text().startswith(ip_url + "\n")
    assert url not in window.qr_description.text()


def test_hotspot_refresh_preserves_domain_and_enables_name_settings(monkeypatch, window):
    from app.hotspot.mobile_windows import MobileHotspotInfo

    window.settings = Settings(_env_file=None, connection_mode="hotspot")
    window._update_mode_controls()
    assert window.local_domain_input.isEnabled()
    assert window.local_domain_method_input.isEnabled()
    assert not window.router_ip_input.isEnabled()
    monkeypatch.setattr(window, "process_is_running", lambda: True)
    window.current_url = "http://otrozhka.local:8000/"
    info = MobileHotspotInfo("Hotspot", "Hotspot", "192.168.137.1")
    window._apply_network_snapshot(gui.NetworkSnapshot(info, False))
    assert window.current_url == "http://otrozhka.local:8000/"
    assert window.site_status.text() == "http://192.168.137.1:8000/"
    write = Mock()
    terminate = Mock()
    monkeypatch.setattr(window.process, "write", write)
    monkeypatch.setattr(window.process, "terminate", terminate)
    window.stop_server()
    write.assert_called_once_with(b"stop\n")
    terminate.assert_not_called()
    monkeypatch.setattr(window, "process_is_running", lambda: False)


def test_dns_setting_requires_confirmed_api_and_invalidates_on_endpoint_change(monkeypatch, window):
    from app.services.router_config import RouterCapability

    assert not window.router_dns_input.isEnabled()
    window.router_api_input.setText("https://192.168.1.1")
    monkeypatch.setattr(window, "_start_worker", lambda function, success, *_: success(function()))
    monkeypatch.setattr(gui, "probe_router", lambda *_: RouterCapability(False, "Unsupported API"))
    window._probe_router()
    assert not window.router_dns_input.isEnabled()
    monkeypatch.setattr(gui, "probe_router", lambda *_: RouterCapability(True, "API supported"))
    window._probe_router()
    assert window.router_dns_input.isEnabled()
    window.local_domain_input.setText("otrozhka.local")
    window.router_dns_input.setChecked(True)
    assert window.local_domain_input.text() == "otrozhka"
    assert window.local_domain_method_input.currentData() == "router_dns"
    assert window.router_apply_button.isEnabled()
    window.router_api_input.setText("https://192.168.2.1")
    assert not window.router_dns_input.isEnabled()
    assert not window.router_apply_button.isEnabled()


def test_portless_setting_is_independent_of_router_api(monkeypatch, window):
    monkeypatch.setattr(window, "_start_worker", lambda function, success, *_: success(function()))
    monkeypatch.setattr(window, "_tcp_port_available", lambda *_: False)
    window._check_port80()
    assert not window.http_without_port_input.isEnabled()
    monkeypatch.setattr(window, "_tcp_port_available", lambda *_: True)
    window._check_port80()
    assert window.http_without_port_input.isEnabled()
    assert not window.router_dns_input.isEnabled()
    window.http_without_port_input.setChecked(True)
    assert not window.port_input.isEnabled()
    window.host_input.setText("192.168.1.20")
    # Даже если занятый порт сохранён, его можно отключить и вернуться к прежнему порту.
    assert window.http_without_port_input.isEnabled()
    window.http_without_port_input.setChecked(False)
    assert window.port_input.isEnabled()


def test_router_launch_checks_actual_port_80(monkeypatch, window):
    window.settings = window.settings.model_copy(update={"http_without_port": True})
    monkeypatch.setattr(gui, "select_router_ip", lambda *_: "192.168.1.20")
    ports = []
    monkeypatch.setattr(
        window, "_tcp_port_available", lambda host, port: ports.append(port) or True
    )
    monkeypatch.setattr(window, "_start_worker", lambda function, success, *_: success(function()))
    monkeypatch.setattr(window.process, "start", Mock())
    window._start_router_server()
    assert ports == [80]
    assert window.process.processEnvironment().value("HTTP_WITHOUT_PORT") == "true"
