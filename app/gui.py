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
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config.env_file import update_env_file
from app.config.settings import PROJECT_ROOT, Settings, get_settings
from app.hotspot.dhcp import CaptiveDhcpServer
from app.hotspot.dns import CaptiveDnsServer
from app.hotspot.mobile_windows import detect_mobile_hotspot, open_mobile_hotspot_settings
from app.hotspot.windows import (
    ensure_firewall_rules_with_elevation,
    ensure_hosted_network_with_elevation,
    stop_hosted_network_with_elevation,
)


class NoWheelSpinBox(QSpinBox):
    """Числовое поле, которое не меняет значение колесом мыши."""

    def wheelEvent(self, event) -> None:  # noqa: N802 - имя метода задаёт Qt
        event.ignore()


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
    auto_created_hotspot: bool = False
    hotspot_error: str | None = None


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
        self.resize(960, 840)

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
        self.app_settings_button = QPushButton("Настройки WiFiDrop")
        self.app_settings_button.setCheckable(True)
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)
        self.open_button.clicked.connect(self.open_site)
        self.settings_button.clicked.connect(open_mobile_hotspot_settings)
        for button in (self.start_button, self.stop_button, self.open_button, self.settings_button, self.app_settings_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        help_label = QLabel(
            "WiFiDrop сначала ищет уже работающий мобильный хот-спот Windows. Если его нет, программа "
            "пытается автоматически создать Wi-Fi сеть с именем и паролем из настроек. Телефон можно "
            "подключить к этой сети и открыть показанный ниже адрес."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        settings_box = QGroupBox("Настройки WiFiDrop (.env)")
        settings_layout = QGridLayout(settings_box)
        self.app_name_input = QLineEdit()
        self.host_input = QLineEdit()
        self.port_input = NoWheelSpinBox()
        self.port_input.setRange(1, 65535)
        self.upload_dir_input = QLineEdit()
        self.max_file_size_input = NoWheelSpinBox()
        self.max_file_size_input.setRange(0, 1_000_000)
        self.max_file_size_input.setSpecialValueText("Без ограничения")
        self.chunk_size_input = NoWheelSpinBox()
        self.chunk_size_input.setRange(64, 16384)
        self.chunk_size_input.setSuffix(" КБ")
        self.log_level_input = QComboBox()
        self.log_level_input.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_input.setToolTip(
            "DEBUG — максимально подробно; INFO — обычная работа; WARNING — предупреждения; "
            "ERROR — только ошибки; CRITICAL — только критические ошибки."
        )
        self.log_dir_input = QLineEdit()
        self.log_retention_input = NoWheelSpinBox()
        self.log_retention_input.setRange(1, 3650)
        self.log_retention_input.setSuffix(" дн.")
        self.captive_enabled_input = QCheckBox("Включать Captive Portal при обычном запуске")
        self.captive_port_input = NoWheelSpinBox()
        self.captive_port_input.setRange(1, 65535)
        self.captive_url_input = QLineEdit()
        self.captive_url_input.setPlaceholderText("Автоматически определить адрес")
        self.hotspot_enabled_input = QCheckBox("Автоматически создавать Wi-Fi сеть, если она не найдена")
        self.hotspot_ssid_input = QLineEdit()
        self.hotspot_password_input = QLineEdit()
        self.hotspot_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_hotspot_password_input = QCheckBox("Показать пароль")
        self.show_hotspot_password_input.toggled.connect(self._set_hotspot_password_visible)
        self.hotspot_gateway_input = QLineEdit()

        settings_rows = [
            ("Название приложения:", self.app_name_input, "Имя, которое отображается на веб-странице."),
            ("Адрес прослушивания:", self.host_input, "Обычно 0.0.0.0 — принимать подключения со всех сетевых интерфейсов."),
            ("Порт сайта:", self.port_input, "TCP-порт, по которому открывается WiFiDrop."),
            ("Папка для файлов:", self.upload_dir_input, "Куда сохранять полученные файлы. Можно указать абсолютный путь."),
            ("Макс. размер файла, МБ:", self.max_file_size_input, "0 означает без ограничения."),
            ("Размер блока загрузки:", self.chunk_size_input, "Размер порции записи файла на диск. Обычно менять не требуется."),
            ("Уровень логов:", self.log_level_input, "Подробность журнала. INFO подходит для обычного использования."),
            ("Папка логов:", self.log_dir_input, "Куда сохранять журналы работы программы."),
            ("Хранить логи:", self.log_retention_input, "Через сколько дней старые журналы удаляются."),
            ("HTTP-порт Captive Portal:", self.captive_port_input, "Обычно 80 — стандартный порт системных проверок Wi-Fi."),
            ("Публичный URL портала:", self.captive_url_input, "Можно оставить пустым для автоматического определения."),
            ("Имя сети:", self.hotspot_ssid_input, "Имя Wi-Fi сети, которую WiFiDrop создаст автоматически при отсутствии подходящего хот-спота."),
            ("Сетевой пароль:", self.hotspot_password_input, "Пароль создаваемой Wi-Fi сети; минимум 8 символов."),
            ("IP создаваемой сети:", self.hotspot_gateway_input, "Локальный адрес компьютера в автоматически создаваемой сети, например 192.168.50.1."),
        ]
        for row, (label_text, widget, tooltip) in enumerate(settings_rows):
            label = QLabel(label_text)
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
            settings_layout.addWidget(label, row, 0)
            if widget is self.hotspot_password_input:
                password_layout = QHBoxLayout()
                password_layout.setContentsMargins(0, 0, 0, 0)
                password_layout.addWidget(widget, 1)
                password_layout.addWidget(self.show_hotspot_password_input)
                settings_layout.addLayout(password_layout, row, 1)
            else:
                settings_layout.addWidget(widget, row, 1)
        settings_layout.addWidget(self.captive_enabled_input, len(settings_rows), 0, 1, 2)
        settings_layout.addWidget(self.hotspot_enabled_input, len(settings_rows) + 1, 0, 1, 2)
        self.save_settings_button = QPushButton("Сохранить настройки")
        self.save_settings_button.clicked.connect(self.save_settings)
        settings_layout.addWidget(self.save_settings_button, len(settings_rows) + 2, 1)
        settings_layout.setColumnStretch(1, 1)
        settings_box.setVisible(False)
        self.app_settings_button.toggled.connect(settings_box.setVisible)
        self.app_settings_button.toggled.connect(
            lambda visible: self.app_settings_button.setText(
                "Скрыть настройки WiFiDrop" if visible else "Настройки WiFiDrop"
            )
        )
        layout.addWidget(settings_box)
        self._load_settings_into_form()

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
        self.dhcp_server: CaptiveDhcpServer | None = None
        self.dhcp_thread: threading.Thread | None = None
        self._auto_created_hotspot = False

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_network_state)
        self.timer.start()
        QTimer.singleShot(0, self.refresh_network_state)

    def _load_settings_into_form(self) -> None:
        settings = self.settings
        self.app_name_input.setText(settings.app_name)
        self.host_input.setText(settings.host)
        self.port_input.setValue(settings.port)
        self.upload_dir_input.setText(str(settings.upload_dir))
        self.max_file_size_input.setValue(settings.max_file_size_mb)
        self.chunk_size_input.setValue(settings.upload_chunk_size_kb)
        self.log_level_input.setCurrentText(settings.log_level)
        self.log_dir_input.setText(str(settings.log_dir))
        self.log_retention_input.setValue(settings.log_retention_days)
        self.captive_enabled_input.setChecked(settings.captive_portal_enabled)
        self.captive_port_input.setValue(settings.captive_portal_port)
        self.captive_url_input.setText(settings.captive_portal_public_url or "")
        self.hotspot_enabled_input.setChecked(settings.auto_create_hotspot)
        self.hotspot_ssid_input.setText(settings.hotspot_ssid)
        self.hotspot_password_input.setText(settings.hotspot_password)
        self.hotspot_gateway_input.setText(settings.hotspot_gateway_ip)

    def save_settings(self) -> None:
        form = {
            "app_name": self.app_name_input.text().strip() or "WiFiDrop",
            "host": self.host_input.text().strip() or "0.0.0.0",
            "port": self.port_input.value(),
            "upload_dir": self.upload_dir_input.text().strip() or "Files",
            "max_file_size_mb": self.max_file_size_input.value(),
            "upload_chunk_size_kb": self.chunk_size_input.value(),
            "log_level": self.log_level_input.currentText(),
            "log_dir": self.log_dir_input.text().strip() or "logs",
            "log_retention_days": self.log_retention_input.value(),
            "captive_portal_enabled": self.captive_enabled_input.isChecked(),
            "captive_portal_port": self.captive_port_input.value(),
            "captive_portal_public_url": self.captive_url_input.text().strip() or None,
            "hotspot_enabled": self.settings.hotspot_enabled,
            "auto_create_hotspot": self.hotspot_enabled_input.isChecked(),
            "hotspot_ssid": self.hotspot_ssid_input.text().strip() or "WiFiDrop",
            "hotspot_password": self.hotspot_password_input.text() or "12347890",
            "hotspot_gateway_ip": self.hotspot_gateway_input.text().strip() or "192.168.50.1",
        }
        try:
            validated = Settings(_env_file=None, **form)
            values = {
                "APP_NAME": validated.app_name,
                "HOST": validated.host,
                "PORT": validated.port,
                "UPLOAD_DIR": form["upload_dir"],
                "MAX_FILE_SIZE_MB": validated.max_file_size_mb,
                "UPLOAD_CHUNK_SIZE_KB": validated.upload_chunk_size_kb,
                "LOG_LEVEL": validated.log_level,
                "LOG_DIR": form["log_dir"],
                "LOG_RETENTION_DAYS": validated.log_retention_days,
                "CAPTIVE_PORTAL_ENABLED": validated.captive_portal_enabled,
                "CAPTIVE_PORTAL_PORT": validated.captive_portal_port,
                "CAPTIVE_PORTAL_PUBLIC_URL": validated.captive_portal_public_url or "",
                "HOTSPOT_ENABLED": validated.hotspot_enabled,
                "AUTO_CREATE_HOTSPOT": validated.auto_create_hotspot,
                "HOTSPOT_SSID": validated.hotspot_ssid,
                "HOTSPOT_PASSWORD": validated.hotspot_password,
                "HOTSPOT_GATEWAY_IP": validated.hotspot_gateway_ip,
            }
            update_env_file(PROJECT_ROOT / ".env", values)
            get_settings.cache_clear()
            self.settings = get_settings()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка настроек", f"Не удалось сохранить настройки:\n{exc}")
            return

        self._load_settings_into_form()
        self.append_log("[GUI] Настройки сохранены в .env.")
        if self.process_is_running():
            QMessageBox.information(
                self,
                "Настройки сохранены",
                "Настройки сохранены. Чтобы они применились к уже запущенному серверу, остановите и снова запустите WiFiDrop.",
            )
        else:
            QMessageBox.information(self, "Настройки сохранены", "Настройки успешно сохранены.")
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
            auto_created = False
            hotspot_error: str | None = None
            if info is None and os.name == "nt" and self.settings.auto_create_hotspot:
                ok, hotspot_error = ensure_hosted_network_with_elevation(
                    self.settings.hotspot_ssid,
                    self.settings.hotspot_password,
                    self.settings.hotspot_gateway_ip,
                )
                if ok:
                    auto_created = True
                    # Помощник уже назначил приватный адрес шлюза; даём адаптеру
                    # немного времени появиться в сетевом API Windows.
                    import time
                    for _ in range(20):
                        info = detect_mobile_hotspot()
                        if info is not None:
                            break
                        time.sleep(0.1)
            if info is None:
                return StartPreflight(None, True, False, None, auto_created, hotspot_error)

            firewall_message: str | None = None
            if os.name == "nt":
                if ensure_firewall_rules_with_elevation(self.settings.port):
                    firewall_message = "[GUI] Правила Windows Firewall для WiFiDrop готовы."
                else:
                    firewall_message = (
                        "[GUI] ПРЕДУПРЕЖДЕНИЕ: правила Windows Firewall не удалось подготовить. "
                        "Если Windows запросила права администратора и запрос был отменён, "
                        "телефон может не получить доступ к WiFiDrop."
                    )

            return StartPreflight(
                info=info,
                captive_tcp_free=self._tcp_port_available("0.0.0.0", self.settings.captive_portal_port),
                dns_port_free=self._udp_port_available(info.ipv4, 53),
                firewall_message=firewall_message,
                auto_created_hotspot=auto_created,
                hotspot_error=hotspot_error,
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
            detail = result.hotspot_error or "Подходящая Wi-Fi сеть не обнаружена."
            QMessageBox.warning(
                self,
                "Не удалось подготовить Wi-Fi сеть",
                f"WiFiDrop попытался создать сеть автоматически, но это не удалось.\n\n{detail}\n\n"
                "Будут открыты штатные настройки «Мобильный хот-спот» Windows.",
            )
            open_mobile_hotspot_settings()
            return

        self._auto_created_hotspot = result.auto_created_hotspot
        if result.auto_created_hotspot:
            self.append_log(
                f"[GUI] Автоматически создана Wi-Fi сеть «{self.settings.hotspot_ssid}» "
                f"с адресом {self.settings.hotspot_gateway_ip}."
            )

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
            self._stop_auto_created_hotspot()
            return

        if self._auto_created_hotspot:
            if not self._udp_port_available("0.0.0.0", 67):
                self.start_button.setEnabled(True)
                QMessageBox.critical(
                    self,
                    "DHCP-порт занят",
                    "UDP-порт 67 занят другой службой. Автоматически созданная сеть не сможет выдавать адреса устройствам.",
                )
                self._stop_auto_created_hotspot()
                return
            try:
                prefix = info.ipv4.rsplit(".", 1)[0]
                self.dhcp_server = CaptiveDhcpServer(
                    info.ipv4,
                    info.ipv4,
                    f"{prefix}.10",
                    f"{prefix}.200",
                )
                self.dhcp_thread = threading.Thread(
                    target=self.dhcp_server.serve_forever,
                    name="wifidrop-hosted-network-dhcp",
                    daemon=True,
                )
                self.dhcp_thread.start()
                self.append_log(f"[GUI] DHCP запущен для автоматически созданной сети {self.settings.hotspot_ssid}.")
            except OSError as exc:
                self.dhcp_server = None
                self.dhcp_thread = None
                self.append_log(f"[GUI] DHCP не запущен: {exc}")

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

    def _stop_auto_created_hotspot(self) -> None:
        if not self._auto_created_hotspot:
            return
        self._auto_created_hotspot = False
        self._start_worker(
            stop_hosted_network_with_elevation,
            lambda ok: self.append_log(
                "[GUI] Автоматически созданная Wi-Fi сеть остановлена." if ok
                else "[GUI] Не удалось автоматически остановить Wi-Fi сеть."
            ),
        )

    def stop_server(self) -> None:
        if not self.process_is_running():
            self._stop_auto_created_hotspot()
            return
        self.append_log("[GUI] Остановка WiFiDrop...")
        self.stop_button.setEnabled(False)
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
            self.dns_thread = None
        if self.dhcp_server is not None:
            self.dhcp_server.stop()
            self.dhcp_server = None
            self.dhcp_thread = None
        self._stop_auto_created_hotspot()
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
        if self.dhcp_server is not None:
            self.dhcp_server.stop()
            self.dhcp_server = None
            self.dhcp_thread = None
        self._stop_auto_created_hotspot()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.site_status.setText("Сервер остановлен")
        self.refresh_network_state()

    def _process_error(self, error: QProcess.ProcessError) -> None:
        self.append_log(f"[GUI] Ошибка процесса: {error.name}")

    def _set_hotspot_password_visible(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.hotspot_password_input.setEchoMode(mode)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.timer.stop()
        if self.dns_server is not None:
            self.dns_server.stop()
            self.dns_server = None
        if self.dhcp_server is not None:
            self.dhcp_server.stop()
            self.dhcp_server = None
        if self.process_is_running():
            self.process.terminate()
            self.process.kill()
        if self._auto_created_hotspot:
            # Приложение уже закрывается, поэтому фонового Qt-цикла для очистки
            # не останется. Останавливаем созданную сеть до выхода.
            stop_hosted_network_with_elevation()
            self._auto_created_hotspot = False
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
