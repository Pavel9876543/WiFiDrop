from __future__ import annotations

import codecs
import os
import socket
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QFont
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

from app.config.settings import PROJECT_ROOT, get_settings
from app.hotspot.dns import CaptiveDnsServer
from app.hotspot.mobile_windows import detect_mobile_hotspot, open_mobile_hotspot_settings
from app.hotspot.windows import ensure_firewall_rules, is_windows_admin


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # pragma: no cover - defensive boundary for GUI workers
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)


@dataclass(frozen=True)
class NetworkSnapshot:
    info: Any | None
    dns_port_free: bool | None


@dataclass(frozen=True)
class StartPreflight:
    info: Any | None
    captive_tcp_free: bool
    dns_port_free: bool
    firewall_message: str | None


class WiFiDropWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = get_settings()
        self.thread_pool = QThreadPool.globalInstance()
        self._network_refresh_running = False
        self._start_preflight_running = False

        self.process = QProcess(self)
        self._process_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)

        self.setWindowTitle("WiFiDrop — сервер и мобильный хот-спот")
        self.resize(900, 650)

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
        self.adapter_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.portal_status.setWordWrap(True)
        status_layout.addWidget(QLabel("Мобильный хот-спот:"), 0, 0)
        status_layout.addWidget(self.hotspot_status, 0, 1)
        status_layout.addWidget(QLabel("Адаптер / IP:"), 1, 0)
        status_layout.addWidget(self.adapter_status, 1, 1)
        status_layout.addWidget(QLabel("Адрес WiFiDrop:"), 2, 0)
        status_layout.addWidget(self.site_status, 2, 1)
        status_layout.addWidget(QLabel("Captive Portal:"), 3, 0)
        status_layout.addWidget(self.portal_status, 3, 1)
        status_layout.setColumnStretch(1, 1)
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
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log_layout.addWidget(self.log)
        layout.addWidget(log_box, 1)

        self.current_url: str | None = None
        self.dns_server: CaptiveDnsServer | None = None
        self.dns_thread: threading.Thread | None = None

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_network_state)
        self.timer.start()
        QTimer.singleShot(0, self.refresh_network_state)

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

    def _start_worker(
        self,
        function: Callable[[], Any],
        on_finished: Callable[[Any], None],
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        worker = FunctionWorker(function)
        worker.signals.finished.connect(on_finished)
        worker.signals.failed.connect(on_failed or self._worker_error)
        self.thread_pool.start(worker)

    def _worker_error(self, message: str) -> None:
        self.append_log(f"[GUI] Фоновая операция завершилась ошибкой: {message}")

    def refresh_network_state(self) -> None:
        if self._network_refresh_running or self._start_preflight_running:
            return
        self._network_refresh_running = True

        def inspect() -> NetworkSnapshot:
            info = detect_mobile_hotspot() if os.name == "nt" else None
            dns_free = None if info is None else self._udp_port_available(info.ipv4, 53)
            return NetworkSnapshot(info=info, dns_port_free=dns_free)

        self._start_worker(inspect, self._apply_network_snapshot, self._network_refresh_failed)

    def _network_refresh_failed(self, message: str) -> None:
        self._network_refresh_running = False
        self.append_log(f"[GUI] Не удалось обновить состояние сети: {message}")

    def _apply_network_snapshot(self, snapshot: NetworkSnapshot) -> None:
        self._network_refresh_running = False
        info = snapshot.info
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
        elif snapshot.dns_port_free:
            self.portal_status.setText("Готов: DNS-порт свободен, Captive Portal включится вместе с сервером")
        else:
            self.portal_status.setText(
                "Ограничен Windows ICS: DHCP/DNS хот-спота занят системой; автоматическое уведомление не гарантируется"
            )

    def process_is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start_server(self) -> None:
        if self.process_is_running() or self._start_preflight_running:
            return
        self._start_preflight_running = True
        self.start_button.setEnabled(False)
        self.append_log("[GUI] Проверка сети и подготовка запуска...")

        def preflight() -> StartPreflight:
            info = detect_mobile_hotspot() if os.name == "nt" else None
            if info is None:
                return StartPreflight(None, True, False, None)

            firewall_message: str | None = None
            if os.name == "nt" and is_windows_admin():
                ensure_firewall_rules(self.settings.port)
                firewall_message = "[GUI] Правила Windows Firewall для WiFiDrop проверены."
            elif os.name == "nt":
                firewall_message = (
                    "[GUI] ПРЕДУПРЕЖДЕНИЕ: GUI запущен без прав администратора; "
                    "Windows Firewall может блокировать телефон."
                )

            return StartPreflight(
                info=info,
                captive_tcp_free=self._tcp_port_available("0.0.0.0", self.settings.captive_portal_port),
                dns_port_free=self._udp_port_available(info.ipv4, 53),
                firewall_message=firewall_message,
            )

        self._start_worker(preflight, self._start_after_preflight, self._start_preflight_failed)

    def _start_preflight_failed(self, message: str) -> None:
        self._start_preflight_running = False
        self.start_button.setEnabled(True)
        self.append_log(f"[GUI] Подготовка запуска завершилась ошибкой: {message}")
        QMessageBox.critical(self, "Ошибка запуска", message)

    def _start_after_preflight(self, result: StartPreflight) -> None:
        self._start_preflight_running = False
        info = result.info
        if info is None:
            self.start_button.setEnabled(True)
            QMessageBox.warning(
                self,
                "Хот-спот не найден",
                "Сначала включите «Мобильный хот-спот» Windows. После его включения WiFiDrop автоматически определит адрес.",
            )
            open_mobile_hotspot_settings()
            return

        if result.firewall_message:
            self.append_log(result.firewall_message)

        if not result.captive_tcp_free:
            self.start_button.setEnabled(True)
            QMessageBox.critical(
                self,
                "Порт Captive Portal занят",
                f"TCP-порт {self.settings.captive_portal_port} уже используется другой программой. "
                "Освободите его и повторите запуск.",
            )
            return

        if result.dns_port_free:
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

        env = QProcessEnvironment.systemEnvironment()
        env.insert("HOTSPOT_ENABLED", "false")
        env.insert("CAPTIVE_PORTAL_ENABLED", "true")
        env.insert("CAPTIVE_PORTAL_PUBLIC_URL", f"http://{info.ipv4}:{self.settings.port}/")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self._process_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.append_log("[GUI] Запуск WiFiDrop для мобильного хот-спота Windows...")
        self.append_log(f"[GUI] Обнаружен адаптер: {info.adapter_name}, IP: {info.ipv4}")
        self.process.start(sys.executable, ["-X", "utf8", str(PROJECT_ROOT / "start.py")])
        self.stop_button.setEnabled(True)
        self.current_url = f"http://{info.ipv4}:{self.settings.port}/"
        self.site_status.setText(self.current_url)
        self.open_button.setEnabled(True)

    def stop_server(self) -> None:
        if not self.process_is_running():
            return
        self.append_log("[GUI] Остановка WiFiDrop...")
        self.stop_button.setEnabled(False)
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
            self.dns_thread = None
        self.process.terminate()
        # Never block the Qt event loop waiting for a child process. If graceful
        # shutdown takes too long, kill it from a timer callback instead.
        QTimer.singleShot(2500, self._kill_process_if_needed)

    def _kill_process_if_needed(self) -> None:
        if self.process_is_running():
            self.append_log("[GUI] Сервер не завершился вовремя — принудительная остановка.")
            self.process.kill()

    def open_site(self) -> None:
        if self.current_url:
            QDesktopServices.openUrl(QUrl(self.current_url))

    def _read_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput())
        # QProcess may split one UTF-8 character between readyRead signals.
        # Incremental decoding preserves incomplete multibyte sequences until
        # the next chunk instead of replacing them with mojibake.
        text = self._process_decoder.decode(data, final=False)
        for line in text.splitlines():
            self.append_log(line)

    def _process_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        tail = self._process_decoder.decode(b"", final=True)
        if tail:
            for line in tail.splitlines():
                self.append_log(line)
        self.append_log(f"[GUI] Сервер завершён. Код: {exit_code}")
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
            self.dns_thread = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.site_status.setText("Сервер остановлен")
        self.refresh_network_state()

    def _process_error(self, error: QProcess.ProcessError) -> None:
        self.append_log(f"[GUI] Ошибка процесса: {error.name}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.timer.stop()
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
        if self.process_is_running():
            self.process.terminate()
            self.process.kill()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    # Segoe UI is present on supported Windows versions and has complete
    # Cyrillic coverage. Qt will fall back to the platform font elsewhere.
    app.setFont(QFont("Segoe UI", 10))
    window = WiFiDropWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
