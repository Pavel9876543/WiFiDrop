from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QUrl

from app.config.settings import PROJECT_ROOT, get_settings
from app.hotspot.dns import CaptiveDnsServer
from app.hotspot.mobile_windows import detect_mobile_hotspot, open_mobile_hotspot_settings
from app.hotspot.windows import ensure_firewall_rules, is_windows_admin


class WiFiDropWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)

        self.setWindowTitle("WiFiDrop — сервер и мобильный хот-спот")
        self.resize(860, 620)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        status_box = QGroupBox("Состояние")
        status_layout = QGridLayout(status_box)
        self.hotspot_status = QLabel("Проверка...")
        self.adapter_status = QLabel("—")
        self.site_status = QLabel("Сервер остановлен")
        self.portal_status = QLabel("—")
        self.site_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_layout.addWidget(QLabel("Мобильный хот-спот:"), 0, 0)
        status_layout.addWidget(self.hotspot_status, 0, 1)
        status_layout.addWidget(QLabel("Адаптер / IP:"), 1, 0)
        status_layout.addWidget(self.adapter_status, 1, 1)
        status_layout.addWidget(QLabel("Адрес WiFiDrop:"), 2, 0)
        status_layout.addWidget(self.site_status, 2, 1)
        status_layout.addWidget(QLabel("Captive Portal:"), 3, 0)
        status_layout.addWidget(self.portal_status, 3, 1)
        layout.addWidget(status_box)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Запустить WiFiDrop")
        self.stop_button = QPushButton("Остановить")
        self.open_button = QPushButton("Открыть сайт")
        self.settings_button = QPushButton("Настройки хот-спота Windows")
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)
        self.open_button.clicked.connect(self.open_site)
        self.settings_button.clicked.connect(open_mobile_hotspot_settings)
        for button in (self.start_button, self.stop_button, self.open_button, self.settings_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        help_label = QLabel(
            "Подключите телефон к мобильному хот-споту Windows. WiFiDrop автоматически определит "
            "внутренний IP хот-спота и покажет точный адрес сайта. Состояние Captive Portal ниже "
            "показывает, может ли WiFiDrop управлять DNS на этом хот-споте."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        log_box = QGroupBox("Журнал")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log)
        layout.addWidget(log_box, 1)

        self.current_url: str | None = None
        self.dns_server: CaptiveDnsServer | None = None
        self.dns_thread: threading.Thread | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_network_state)
        self.timer.start()
        self.refresh_network_state()

    def append_log(self, text: str) -> None:
        text = text.rstrip("\r\n")
        if text:
            self.log.appendPlainText(text)

    @staticmethod
    def _tcp_port_available(ip: str, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((ip, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    @staticmethod
    def _udp_port_available(ip: str, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((ip, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def refresh_network_state(self) -> None:
        info = detect_mobile_hotspot() if os.name == "nt" else None
        if info is None:
            self.hotspot_status.setText("Не обнаружен")
            self.adapter_status.setText("Включите мобильный хот-спот Windows и подключите Wi-Fi адаптер")
            if not self.process_is_running():
                self.site_status.setText("Сервер остановлен")
                self.current_url = None
                self.open_button.setEnabled(False)
            self.portal_status.setText("Недоступен: хот-спот не обнаружен")
            return

        self.hotspot_status.setText("Работает")
        self.adapter_status.setText(f"{info.adapter_name} — {info.ipv4}")
        self.current_url = f"http://{info.ipv4}:{self.settings.port}/"
        if self.process_is_running():
            self.site_status.setText(self.current_url)
            self.open_button.setEnabled(True)

        if self.dns_server is not None:
            self.portal_status.setText("Активен: DNS-перехват + HTTP Captive Portal")
        elif self._udp_port_available(info.ipv4, 53):
            self.portal_status.setText("Готов: DNS-порт свободен, Captive Portal включится вместе с сервером")
        else:
            self.portal_status.setText(
                "Ограничен Windows ICS: DHCP/DNS хот-спота занят системой; автоматическое уведомление не гарантируется"
            )

    def process_is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start_server(self) -> None:
        if self.process_is_running():
            return
        info = detect_mobile_hotspot() if os.name == "nt" else None
        if info is None:
            QMessageBox.warning(
                self,
                "Хот-спот не найден",
                "Сначала включите «Мобильный хот-спот» Windows. После его включения WiFiDrop автоматически определит адрес.",
            )
            open_mobile_hotspot_settings()
            return

        if os.name == "nt" and is_windows_admin():
            ensure_firewall_rules(self.settings.port)
            self.append_log("[GUI] Правила Windows Firewall для WiFiDrop проверены.")
        elif os.name == "nt":
            self.append_log("[GUI] ПРЕДУПРЕЖДЕНИЕ: GUI запущен без прав администратора; Windows Firewall может блокировать телефон.")

        if not self._tcp_port_available("0.0.0.0", self.settings.captive_portal_port):
            QMessageBox.critical(
                self,
                "Порт Captive Portal занят",
                f"TCP-порт {self.settings.captive_portal_port} уже используется другой программой. "
                "Освободите его и повторите запуск.",
            )
            return

        # In Windows Mobile Hotspot clients normally use the private gateway as DNS.
        # If ICS did not reserve UDP/53 on that address, WiFiDrop can answer all A
        # queries with the portal IP. Android/iOS connectivity probes then reach
        # our HTTP listener on port 80 and the OS can show its captive-portal UI.
        if self._udp_port_available(info.ipv4, 53):
            try:
                self.dns_server = CaptiveDnsServer(info.ipv4, info.ipv4)
                self.dns_thread = threading.Thread(
                    target=self.dns_server.serve_forever,
                    name="wifidrop-mobile-hotspot-dns",
                    daemon=True,
                )
                self.dns_thread.start()
                self.append_log(f"[GUI] Captive DNS запущен на {info.ipv4}:53.")
                self.portal_status.setText("Активен: DNS-перехват + HTTP Captive Portal")
            except OSError as exc:
                self.dns_server = None
                self.dns_thread = None
                self.append_log(f"[GUI] Captive DNS не запущен: {exc}")
        else:
            self.append_log(
                "[GUI] UDP/53 занят Windows ICS. Сайт будет доступен по адресу ниже, "
                "но системное уведомление Captive Portal на этом режиме Windows не гарантируется."
            )

        env = self.process.processEnvironment()
        if env.isEmpty():
            from PyQt6.QtCore import QProcessEnvironment
            env = QProcessEnvironment.systemEnvironment()
        env.insert("HOTSPOT_ENABLED", "false")
        env.insert("CAPTIVE_PORTAL_ENABLED", "true")
        env.insert("CAPTIVE_PORTAL_PUBLIC_URL", f"http://{info.ipv4}:{self.settings.port}/")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self.append_log("[GUI] Запуск WiFiDrop для мобильного хот-спота Windows...")
        self.append_log(f"[GUI] Обнаружен адаптер: {info.adapter_name}, IP: {info.ipv4}")
        self.process.start(sys.executable, [str(PROJECT_ROOT / "start.py")])
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.current_url = f"http://{info.ipv4}:{self.settings.port}/"
        self.site_status.setText(self.current_url)
        self.open_button.setEnabled(True)

    def stop_server(self) -> None:
        if not self.process_is_running():
            return
        self.append_log("[GUI] Остановка WiFiDrop...")
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
            self.dns_thread = None
        self.process.terminate()
        if not self.process.waitForFinished(2500):
            self.process.kill()

    def open_site(self) -> None:
        if self.current_url:
            QDesktopServices.openUrl(QUrl(self.current_url))

    def _read_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.append_log(line)

    def _process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        self.append_log(f"[GUI] Сервер завершён. Код: {exit_code}")
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
            self.dns_thread = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.site_status.setText("Сервер остановлен")

    def _process_error(self, error: QProcess.ProcessError) -> None:
        self.append_log(f"[GUI] Ошибка процесса: {error.name}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.process_is_running():
            self.stop_server()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = WiFiDropWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
