from __future__ import annotations

from unittest.mock import Mock

import pytest


@pytest.fixture(scope="module")
def qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_gui_router_start_and_stop_without_hotspot(qt_app, monkeypatch, tmp_path):
    from PyQt6.QtCore import QProcess

    from app import gui
    from app.config.settings import Settings
    from app.services.router_connection import save_url_qr

    settings = Settings(
        _env_file=None, connection_mode="router", hotspot_enabled=True, captive_portal_enabled=True
    )
    monkeypatch.setattr(gui, "get_settings", lambda: settings)
    monkeypatch.setattr(gui, "get_local_ipv4_addresses", lambda: ["192.168.1.42"])
    monkeypatch.setattr(gui, "select_router_ip", lambda _: "192.168.1.42")
    for function in [
        "detect_mobile_hotspot",
        "ensure_hosted_network_with_elevation",
        "ensure_firewall_rules_with_elevation",
    ]:
        monkeypatch.setattr(gui, function, Mock(side_effect=AssertionError(function)))
    connection = Mock(
        address="192.168.1.42",
        ip_url="http://192.168.1.42:8000/",
        url="http://otrozhka.local:8000/",
        display_url="http://otrozhka.local:8000/",
        name_available=True,
        qr_path=save_url_qr("http://otrozhka.local:8000/", root=tmp_path),
    )
    monkeypatch.setattr(gui, "RouterConnection", Mock(return_value=connection))
    window = gui.WiFiDropWindow()
    window.timer.stop()
    state = [QProcess.ProcessState.NotRunning]
    process = Mock()
    process.state.side_effect = lambda: state[0]
    process.start.side_effect = lambda *_: state.__setitem__(0, QProcess.ProcessState.Running)
    window.process = process
    monkeypatch.setattr(window, "_tcp_port_available", lambda *_: True)
    monkeypatch.setattr(window, "_start_worker", lambda fn, ok, *args: ok(fn()))
    window.start_server()
    assert window.site_status.text() == connection.ip_url
    assert window.domain_status.text() == connection.display_url
    assert not window.qr_label.pixmap().isNull()
    assert not window.mode_input.isEnabled()
    env = process.setProcessEnvironment.call_args.args[0]
    assert env.value("CONNECTION_MODE") == "router"
    assert env.value("CAPTIVE_PORTAL_ENABLED") == "false"
    assert window.dns_server is None
    assert window.dhcp_server is None
    window.stop_server()
    connection.close.assert_called_once()
    state[0] = QProcess.ProcessState.NotRunning
    window._process_finished(0, QProcess.ExitStatus.NormalExit)
    assert window.mode_input.isEnabled()
    assert window.settings_box.isEnabled()
    assert window.qr_label.pixmap().isNull()
    window.close()


def test_gui_saves_router_settings_and_cyrillic_name(qt_app, monkeypatch, tmp_path):
    from app import gui
    from app.config.settings import Settings

    settings = Settings(_env_file=None, connection_mode="router")
    getter = Mock(return_value=settings)
    monkeypatch.setattr(gui, "get_settings", getter)
    monkeypatch.setattr(gui, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(gui, "get_local_ipv4_addresses", lambda: ["192.168.1.42"])
    monkeypatch.setattr(gui.QMessageBox, "information", Mock())
    window = gui.WiFiDropWindow()
    window.timer.stop()
    window.local_name_input.setText("Отрожка")
    window.router_ip_input.setCurrentIndex(1)
    window.save_settings()
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "CONNECTION_MODE=router" in content
    assert "LOCAL_NAME=отрожка" in content
    assert "ROUTER_IP=192.168.1.42" in content
    assert "LOCAL_NAME_MODE=mdns" in content
    window.close()
