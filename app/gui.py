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
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
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
from app.services.router_connection import RouterConnection, select_router_ip
from app.utils.network import get_local_ipv4_addresses


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
        self.router_connection: RouterConnection | None = None

        self.process = QProcess(self)
        self._process_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)

        self.setWindowTitle("WiFiDrop — хот-спот и роутер")
        self.resize(960, 840)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        mode_row = QHBoxLayout()
        self.mode_input = QComboBox()
        self.mode_input.addItem("Мобильный хот-спот", "hotspot")
        self.mode_input.addItem("Роутер (общая локальная сеть)", "router")
        self.mode_input.setCurrentIndex(1 if self.settings.connection_mode == "router" else 0)
        mode_row.addWidget(QLabel("Режим запуска:"))
        mode_row.addWidget(self.mode_input, 1)
        layout.addLayout(mode_row)

        status_box = QGroupBox("Состояние")
        status_layout = QGridLayout(status_box)
        self.hotspot_status = QLabel("Проверка...")
        self.adapter_status = QLabel("—")
        self.site_status = QLabel("Сервер остановлен")
        self.portal_status = QLabel("—")
        self.domain_status = QLabel("—")
        self.domain_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.domain_status.setWordWrap(True)
        self.qr_label = QLabel("QR появится после запуска через роутер")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(240, 240)
        self.qr_label.setVisible(self.settings.connection_mode == "router")
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
        status_layout.addWidget(QLabel("Локальное имя:"), 4, 0)
        status_layout.addWidget(self.domain_status, 4, 1)
        status_layout.addWidget(self.qr_label, 0, 2, 5, 1)
        status_layout.setColumnStretch(1, 1)
        layout.addWidget(status_box)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Запустить WiFiDrop")
        self.stop_button = QPushButton("Остановить")
        self.open_button = QPushButton("Открыть сайт")
        self.settings_button = QPushButton("Настройки хот-спота Windows")
        self.app_settings_button = QPushButton("Настройки WiFiDrop")
        self.instructions_button = QPushButton("Инструкции")
        self.app_settings_button.setCheckable(True)
        self.stop_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_server)
        self.stop_button.clicked.connect(self.stop_server)
        self.open_button.clicked.connect(self.open_site)
        self.settings_button.clicked.connect(open_mobile_hotspot_settings)
        self.instructions_button.clicked.connect(self.show_instructions)
        for button in (
            self.start_button,
            self.stop_button,
            self.open_button,
            self.settings_button,
            self.app_settings_button,
            self.instructions_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        settings_box = QGroupBox("Настройки WiFiDrop (.env)")
        self.settings_box = settings_box
        settings_layout = QGridLayout(settings_box)
        self.router_ip_input = QComboBox()
        self.router_ip_input.addItem("Автоматически", "")
        for address in get_local_ipv4_addresses():
            self.router_ip_input.addItem(address, address)
        self.local_name_mode_input = QComboBox()
        self.local_name_mode_input.addItem("Автоматически через .local (mDNS)", "mdns")
        self.local_name_mode_input.addItem("DNS роутера (настроить вручную)", "dns")
        self.local_name_input = QLineEdit()
        self.local_name_input.setPlaceholderText("Необязательно: otrozhka или отрожка")
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
            ("IP компьютера в сети роутера:", self.router_ip_input,
             "Выберите адрес компьютера, а не роутера. Автоматически — адрес основного маршрута."),
            ("Способ доступа по имени:", self.local_name_mode_input,
             "mDNS — имя.local; DNS — заранее настройте соответствие имени и IP в роутере."),
            ("Локальное имя:", self.local_name_input,
             "Без http:// и порта. Кириллица поддерживается; для DNS допустим полный домен."),
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
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_box)
        settings_scroll.setMinimumHeight(220)
        settings_scroll.setMaximumHeight(420)
        settings_scroll.setVisible(False)
        self.app_settings_button.toggled.connect(settings_scroll.setVisible)
        self.app_settings_button.toggled.connect(
            lambda visible: self.app_settings_button.setText(
                "Скрыть настройки WiFiDrop" if visible else "Настройки WiFiDrop"
            )
        )
        layout.addWidget(settings_scroll)
        self._load_settings_into_form()
        self.mode_input.currentIndexChanged.connect(self._change_mode)
        self._update_mode_controls()

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
        self.local_name_input.setText(settings.local_name or "")
        self.local_name_mode_input.setCurrentIndex(1 if settings.local_name_mode == "dns" else 0)
        index = self.router_ip_input.findData(settings.router_ip or "")
        if index < 0:
            self.router_ip_input.addItem(settings.router_ip, settings.router_ip)
            index = self.router_ip_input.count() - 1
        self.router_ip_input.setCurrentIndex(index)
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
            "connection_mode": self.mode_input.currentData(),
            "router_ip": self.router_ip_input.currentData() or None,
            "local_name": self.local_name_input.text().strip() or None,
            "local_name_mode": self.local_name_mode_input.currentData(),
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
                "CONNECTION_MODE": validated.connection_mode,
                "ROUTER_IP": validated.router_ip or "",
                "LOCAL_NAME": validated.local_name or "",
                "LOCAL_NAME_MODE": validated.local_name_mode,
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
        self._update_mode_controls()
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

    def _change_mode(self) -> None:
        mode = self.mode_input.currentData()
        try:
            update_env_file(PROJECT_ROOT / ".env", {"CONNECTION_MODE": mode})
        except OSError as exc:
            self.mode_input.blockSignals(True)
            self.mode_input.setCurrentIndex(1 if self.settings.connection_mode == "router" else 0)
            self.mode_input.blockSignals(False)
            QMessageBox.critical(self, "Ошибка настроек", f"Не удалось сохранить режим:\n{exc}")
            return
        get_settings.cache_clear()
        self.settings = get_settings()
        self._update_mode_controls()
        self.qr_label.clear()
        self.qr_label.setText("QR появится после запуска через роутер")
        self.domain_status.setText("—")
        self.refresh_network_state()

    def _update_mode_controls(self) -> None:
        router = self.mode_input.currentData() == "router"
        self.qr_label.setVisible(router)
        self.router_ip_input.setEnabled(router)
        self.local_name_input.setEnabled(router)
        self.local_name_mode_input.setEnabled(router)
        self.settings_button.setEnabled(not router)
        for widget in (self.captive_enabled_input, self.captive_port_input,
                       self.captive_url_input, self.hotspot_enabled_input,
                       self.hotspot_ssid_input, self.hotspot_password_input,
                       self.hotspot_gateway_input, self.show_hotspot_password_input):
            widget.setEnabled(not router)

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

        if self.settings.connection_mode == "router":
            self._network_refresh_running = False
            self.hotspot_status.setText("Не используется (режим роутера)")
            self.portal_status.setText("Выключен в режиме роутера")
            if self.router_connection is not None:
                self.adapter_status.setText(self.router_connection.address)
            else:
                addresses = get_local_ipv4_addresses()
                self.adapter_status.setText(", ".join(addresses) or "Подключитесь к сети роутера")
                existing = {self.router_ip_input.itemData(i)
                            for i in range(self.router_ip_input.count())}
                for address in addresses:
                    if address not in existing:
                        self.router_ip_input.addItem(address, address)
            return

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
        if self.settings.connection_mode == "router":
            self.refresh_network_state()
            return
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

        if not self.settings.captive_portal_enabled:
            self.portal_status.setText("Выключен в настройках")
        elif self.dns_server is not None:
            self.portal_status.setText("Активен: DNS-перехват + HTTP Captive Portal")
        elif snapshot.dns_port_free:
            self.portal_status.setText("Готов: DNS-порт свободен, Captive Portal включится вместе с сервером")
        else:
            self.portal_status.setText(
                "Ограничен Windows ICS: DHCP/DNS хот-спота занят системой; автоматическое уведомление не гарантируется"
            )

    def show_instructions(self) -> None:
        """Открывает подробную инструкцию в отдельном окне."""

        dialog = QDialog(self)
        dialog.setWindowTitle("Инструкции WiFiDrop")
        dialog.resize(780, 700)
        dialog.setMinimumSize(560, 480)

        dialog_layout = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("<h2>Инструкции WiFiDrop</h2>")
        content_layout.addWidget(title)

        router_help = QLabel(
            "<b>Режим роутера</b><br>Подключите компьютер и телефон к одному роутеру. "
            "Выберите режим «Роутер», затем в настройках при необходимости выберите IP компьютера "
            "и локальное имя. Сохраните настройки и запустите сервер. Введите полный HTTP-адрес "
            "из окна или отсканируйте QR. Изображение WiFiDrop_QR.png сохраняется в корне проекта.<br><br>"
            "Имя otrozhka даёт адрес http://otrozhka.local:8000/ (порт зависит от настроек). "
            "Поддерживается и кириллица, например отрожка; QR использует совместимую запись IDNA. "
            "Для имени нужен mDNS и отсутствие изоляции клиентов Wi-Fi; иначе используйте IP. "
            "Для http://otrozhka:8000/ выберите DNS и заранее настройте в роутере запись "
            "otrozhka → IP компьютера. Для кириллицы DNS-запись задаётся в IDNA (xn--…). "
            "Приложение проверит адрес имени и при ошибке выдаст QR по IP.<br><br>"
            "Одно слово без http:// может стать поисковым запросом. Автоматического открытия "
            "на телефоне в режиме роутера нет. Сервер работает на компьютере, а не на самом роутере."
        )
        router_help.setWordWrap(True)
        router_help.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(router_help)
        usage = QLabel(
            "<b>Как пользоваться</b><br><br>"
            "1. Нажмите <b>«Запустить WiFiDrop»</b>. Программа найдёт работающий мобильный хот-спот Windows. "
            "Если подходящей сети нет и включено автоматическое создание сети, WiFiDrop попробует создать её самостоятельно.<br><br>"
            "2. На телефоне, планшете или другом устройстве откройте настройки Wi-Fi и подключитесь к сети, "
            "имя которой указано в поле <b>«Имя сети»</b>. Введите пароль из поля <b>«Сетевой пароль»</b>.<br><br>"
            "3. Если Captive Portal включён, устройство может автоматически показать системное окно входа в сеть "
            "с WiFiDrop. Если окно не появилось, откройте обычный браузер и введите адрес из строки "
            "<b>«Адрес WiFiDrop»</b> в основном окне программы.<br><br>"
            "4. Если Captive Portal выключен, автоматическое captive-окно и DNS-перехват не запускаются. "
            "Это не отключает сам WiFiDrop: сайт нужно открыть вручную по адресу из основного окна.<br><br>"
            "5. На странице WiFiDrop нажмите на область выбора файлов или перетащите файлы в неё с компьютера. "
            "После выбора проверьте список и запустите загрузку.<br><br>"
            "6. Полученные файлы сохраняются в папку, указанную в поле <b>«Папка для файлов»</b>."
        )
        usage.setWordWrap(True)
        usage.setTextFormat(Qt.TextFormat.RichText)
        usage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(usage)

        settings_help = QLabel(
            "<br><b>Описание настроек</b><br><br>"
            "<b>Название приложения</b> — название, которое отображается на веб-странице. "
            "Обычно менять не требуется; рекомендуемое значение — WiFiDrop.<br><br>"
            "<b>Адрес прослушивания</b> — определяет, на каких сетевых интерфейсах компьютер принимает подключения. "
            "Рекомендуется <code>0.0.0.0</code>, чтобы телефон мог подключиться к WiFiDrop. "
            "Например, <code>127.0.0.1</code> сделает сайт доступным только на самом компьютере.<br><br>"
            "<b>Порт сайта</b> — TCP-порт основного сайта WiFiDrop. Телефон подключается к адресу вида IP:порт. "
            "Оставьте значение по умолчанию, если этот порт не занят другой программой.<br><br>"
            "<b>Папка для файлов</b> — папка на компьютере, куда сохраняются полученные файлы. "
            "У программы должны быть права на запись в неё.<br><br>"
            "<b>Макс. размер файла, МБ</b> — максимальный разрешённый размер одного файла. "
            "0 означает отсутствие ограничения. Файл больше установленного значения будет отклонён.<br><br>"
            "<b>Размер блока загрузки</b> — размер порции данных при записи файла на диск. "
            "Это техническая настройка, которую обычному пользователю менять не требуется.<br><br>"
            "<b>Уровень логов</b> — подробность журнала: <code>DEBUG</code> — максимальная диагностика; "
            "<code>INFO</code> — обычная работа и рекомендуемое значение; <code>WARNING</code> — предупреждения и ошибки; "
            "<code>ERROR</code> — ошибки; <code>CRITICAL</code> — только критические ошибки.<br><br>"
            "<b>Папка логов</b> — место хранения журналов работы программы. Они нужны для диагностики неисправностей.<br><br>"
            "<b>Хранить логи</b> — сколько дней сохранять старые журналы перед автоматическим удалением.<br><br>"
            "<b>HTTP-порт Captive Portal</b> — порт системных проверок сети и captive-портала. "
            "Обычно используется 80; без необходимости менять его не рекомендуется.<br><br>"
            "<b>Публичный URL портала</b> — адрес, на который Captive Portal направляет подключённое устройство. "
            "Обычно оставьте поле пустым, чтобы WiFiDrop определил адрес автоматически.<br><br>"
            "<b>Включать Captive Portal при обычном запуске</b> — включает captive-механизмы и DNS-перехват, "
            "которые помогают телефону автоматически обнаружить WiFiDrop. При выключенном флажке они не запускаются, "
            "а WiFiDrop открывается вручную по адресу из основного окна. Для обычного использования рекомендуется включить.<br><br>"
            "<b>Автоматически создавать Wi-Fi сеть, если она не найдена</b> — позволяет WiFiDrop попытаться создать "
            "Wi-Fi сеть самостоятельно, если подходящий хот-спот Windows отсутствует. При выключении сеть нужно подготовить вручную.<br><br>"
            "<b>Имя сети</b> — SSID автоматически создаваемой Wi-Fi сети, который будет виден на телефоне. "
            "По умолчанию — <code>WiFiDrop</code>.<br><br>"
            "<b>Сетевой пароль</b> — пароль автоматически создаваемой сети. Он должен содержать не менее 8 символов.<br><br>"
            "<b>Показать пароль</b> — показывает или скрывает пароль в поле GUI; само значение пароля не изменяет.<br><br>"
            "<b>IP создаваемой сети</b> — локальный IP компьютера в автоматически создаваемой сети. "
            "Рекомендуется оставить <code>192.168.50.1</code>, если нет конфликта с другой сетью.<br><br>"
            "<b>Сохранить настройки</b> — сохраняет введённые значения в конфигурацию WiFiDrop. "
            "После изменения сетевых параметров остановите и снова запустите WiFiDrop.<br><br>"
            "<b>Что обычно нужно менять</b> — обычному пользователю достаточно выбрать папку для файлов и, "
            "при необходимости, изменить имя и пароль Wi-Fi сети. Остальные технические параметры лучше оставить по умолчанию."
        )
        settings_help.setWordWrap(True)
        settings_help.setTextFormat(Qt.TextFormat.RichText)
        settings_help.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(settings_help)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        dialog_layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)

        dialog.exec()

    def process_is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start_server(self) -> None:
        if self.process_is_running() or self._start_preflight_running:
            return
        if self.settings.connection_mode == "router":
            self._start_router()
            return
        self._start_preflight_running = True
        self.mode_input.setEnabled(False)
        self.app_settings_button.setEnabled(False)
        self.settings_box.setEnabled(False)
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
                captive_tcp_free=(
                    self._tcp_port_available("0.0.0.0", self.settings.captive_portal_port)
                    if self.settings.captive_portal_enabled else True
                ),
                dns_port_free=(
                    self._udp_port_available(info.ipv4, 53)
                    if self.settings.captive_portal_enabled else False
                ),
                firewall_message=firewall_message,
                auto_created_hotspot=auto_created,
                hotspot_error=hotspot_error,
            )

        self._start_worker(preflight, self._start_after_preflight, self._start_preflight_failed)

    def _start_preflight_failed(self, message: str) -> None:
        self._start_preflight_running = False
        self.start_button.setEnabled(True)
        self.mode_input.setEnabled(True)
        self.app_settings_button.setEnabled(True)
        self.settings_box.setEnabled(True)
        self.qr_label.clear()
        self.qr_label.setText("Запуск не выполнен")
        self.append_log(f"[GUI] Подготовка запуска завершилась ошибкой: {message}")
        QMessageBox.critical(self, "Ошибка запуска", message)

    def _start_after_preflight(self, result: StartPreflight) -> None:
        self._start_preflight_running = False
        info = result.info
        if info is None:
            self.mode_input.setEnabled(True)
            self.app_settings_button.setEnabled(True)
            self.settings_box.setEnabled(True)
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

        if self.settings.captive_portal_enabled and not result.captive_tcp_free:
            self.mode_input.setEnabled(True)
            self.app_settings_button.setEnabled(True)
            self.settings_box.setEnabled(True)
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
                self.mode_input.setEnabled(True)
                self.app_settings_button.setEnabled(True)
                self.settings_box.setEnabled(True)
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
                    captive_portal_enabled=self.settings.captive_portal_enabled,
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

        if self.settings.captive_portal_enabled:
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
        else:
            self.portal_status.setText("Выключен в настройках")
            self.append_log("[GUI] Captive Portal выключен: DNS-перехват и captive HTTP listener не запускаются.")

        env = QProcessEnvironment.systemEnvironment()
        env.insert("CONNECTION_MODE", "hotspot")
        env.remove("WIFIDROP_GUI_ROUTER")
        env.insert("HOTSPOT_ENABLED", "false")
        env.insert("CAPTIVE_PORTAL_ENABLED", "true" if self.settings.captive_portal_enabled else "false")
        if self.settings.captive_portal_enabled:
            env.insert("CAPTIVE_PORTAL_PUBLIC_URL", f"http://{info.ipv4}:{self.settings.port}/")
        else:
            env.remove("CAPTIVE_PORTAL_PUBLIC_URL")
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

    def _start_router(self) -> None:
        self._start_preflight_running = True
        self.start_button.setEnabled(False)
        self.mode_input.setEnabled(False)
        self.app_settings_button.setEnabled(False)
        self.settings_box.setEnabled(False)
        self.qr_label.clear()
        self.qr_label.setText("Подготовка QR…")

        def prepare() -> tuple[RouterConnection, list[str]]:
            select_router_ip(self.settings)
            if not self._tcp_port_available(self.settings.host, self.settings.port):
                raise ValueError(f"TCP-порт {self.settings.port} занят другой программой")
            messages: list[str] = []
            connection = RouterConnection(self.settings, messages.append)
            connection.start()
            return connection, messages

        self._start_worker(prepare, self._router_prepared, self._start_preflight_failed)

    def _router_prepared(self, result: tuple[RouterConnection, list[str]]) -> None:
        self._start_preflight_running = False
        connection, messages = result
        self.router_connection = connection
        for message in messages:
            self.append_log(message)
        self.current_url = connection.url
        self.site_status.setText(connection.ip_url)
        self.adapter_status.setText(connection.address)
        self.domain_status.setText(connection.display_url if connection.name_available else "Не используется")
        if connection.qr_path:
            pixmap = QPixmap(str(connection.qr_path))
            # Масштаб целым числом сохраняет чёткую сетку модулей QR.
            modules = max(1, pixmap.width() // 8)
            size = modules * max(1, 240 // modules)
            self.qr_label.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.FastTransformation))
        else:
            self.qr_label.setText("QR не сохранён — используйте адрес выше")
        env = QProcessEnvironment.systemEnvironment()
        env.insert("CONNECTION_MODE", "router")
        env.insert("HOTSPOT_ENABLED", "false")
        env.insert("CAPTIVE_PORTAL_ENABLED", "false")
        env.insert("WIFIDROP_GUI_ROUTER", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(PROJECT_ROOT))
        self._process_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.process.start(sys.executable, ["-X", "utf8", str(PROJECT_ROOT / "start.py")])
        self.stop_button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.portal_status.setText("Выключен в режиме роутера")
        self.append_log("[GUI] Если Windows Firewall запросит доступ, разрешите его для частной сети.")

    def _close_router_connection(self) -> None:
        if self.router_connection is not None:
            self.router_connection.close()
            self.router_connection = None

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
        self._close_router_connection()
        self.qr_label.clear()
        self.qr_label.setText("Сервер остановлен")
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
        self._close_router_connection()
        self.qr_label.clear()
        self.qr_label.setText("Сервер остановлен")
        self.domain_status.setText("—")
        self.mode_input.setEnabled(True)
        self.app_settings_button.setEnabled(True)
        self.settings_box.setEnabled(True)
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
        if error == QProcess.ProcessError.FailedToStart:
            self._process_finished(-1, QProcess.ExitStatus.CrashExit)

    def _set_hotspot_password_visible(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.hotspot_password_input.setEchoMode(mode)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._start_preflight_running:
            self.append_log("[GUI] Дождитесь завершения подготовки запуска перед закрытием.")
            event.ignore()
            return
        self.timer.stop()
        self._close_router_connection()
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
