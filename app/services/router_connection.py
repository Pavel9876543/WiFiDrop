from __future__ import annotations

import socket
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import qrcode
from zeroconf import DNSAddress, DNSOutgoing, DNSQuestion, IPVersion, ServiceInfo, Zeroconf

from app.config.settings import PROJECT_ROOT, Settings
from app.utils.local_name import local_hostname
from app.utils.network import get_local_ipv4_addresses, get_preferred_local_ipv4_address

QR_FILENAME = "WiFiDrop_QR.png"


def select_router_ip(settings: Settings) -> str:
    addresses = get_local_ipv4_addresses()
    address = settings.router_ip or get_preferred_local_ipv4_address()
    if not address or address not in addresses:
        raise ValueError(
            "IP компьютера в сети роутера не найден. Подключитесь к сети и выберите IP."
        )
    if settings.host not in {"0.0.0.0", address}:
        raise ValueError(
            "Для режима роутера адрес прослушивания должен быть 0.0.0.0 или выбранный IP."
        )
    return address


def save_url_qr(url: str, root: Path = PROJECT_ROOT) -> Path:
    """Сохраняет QR атомарно в корень проекта, а не в текущую рабочую папку."""
    target = root / QR_FILENAME
    with tempfile.NamedTemporaryFile(
        prefix=".wifidrop-qr-", suffix=".png", dir=root, delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        image = qrcode.make(
            url, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4
        )
        image.save(temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


class LocalNamePublisher:
    """Публикует одно .local имя на выбранном интерфейсе без DNS-перехвата."""

    def __init__(self, name: str, address: str, port: int) -> None:
        self.hostname = local_hostname(name)
        self.address = address
        self.port = port
        self.zc: Zeroconf | None = None
        self.info: ServiceInfo | None = None

    def start(self) -> None:
        self.zc = Zeroconf(interfaces=[self.address], ip_version=IPVersion.V4Only)
        try:
            # Проверяем также A-запись имени хоста: библиотека проверяет конфликт
            # имени сервиса, но другой хост может вообще не публиковать HTTP-сервис.
            server = self.hostname + "."
            for _ in range(3):
                query = DNSOutgoing(0)  # RFC 6762: multicast query, A / IN.
                query.add_question(DNSQuestion(server, 1, 1))
                self.zc.send(query)
                time.sleep(0.25)
                for record in self.zc.cache.entries_with_name(server):
                    if (
                        isinstance(record, DNSAddress)
                        and record.type == 1
                        and not record.is_expired(time.monotonic() * 1000)
                        and record.address != socket.inet_aton(self.address)
                    ):
                        raise ValueError(f"Имя {self.hostname} уже используется в сети")
            self.info = ServiceInfo(
                "_http._tcp.local.",
                f"{self.hostname}._http._tcp.local.",
                addresses=[socket.inet_aton(self.address)],
                port=self.port,
                properties={"path": "/"},
                server=server,
                host_ttl=30,
            )
            self.zc.register_service(self.info, allow_name_change=False)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        zc, self.zc = self.zc, None
        if zc is not None:
            try:
                if self.info is not None:
                    zc.unregister_service(self.info)
            finally:
                zc.close()
        self.info = None


class RouterConnection:
    def __init__(self, settings: Settings, report: Callable[[str], None] = print) -> None:
        self.settings = settings
        self.report = report
        self.address = select_router_ip(settings)
        self.ip_url = f"http://{self.address}:{settings.port}/"
        self.url = self.ip_url
        self.display_url = self.ip_url
        self.qr_path: Path | None = None
        self.publisher: LocalNamePublisher | None = None
        self.name_available = False

    def start(self) -> None:
        self.report(f"[WiFiDrop] Режим роутера. IP: {self.ip_url}")
        if self.settings.local_name:
            try:
                if self.settings.local_name_mode == "dns":
                    hostname = local_hostname(self.settings.local_name, "dns")
                    resolved = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
                    addresses = {item[4][0] for item in resolved}
                    if addresses != {self.address}:
                        raise ValueError(f"Настройте DNS роутера: {hostname} → {self.address}")
                    display_name = self.settings.local_name
                else:
                    publisher = LocalNamePublisher(
                        self.settings.local_name, self.address, self.settings.port
                    )
                    publisher.start()
                    self.publisher = publisher
                    hostname = publisher.hostname
                    display_name = self.settings.local_name + ".local"
            except Exception as exc:
                self.report(f"[WiFiDrop] Локальное имя недоступно: {exc}. Используйте IP.")
            else:
                self.name_available = True
                self.url = f"http://{hostname}:{self.settings.port}/"
                self.display_url = f"http://{display_name}:{self.settings.port}/"
                self.report(f"[WiFiDrop] Домен: {self.display_url}")
                self.report(f"[WiFiDrop] URL для QR: {self.url}")
        else:
            self.report("[WiFiDrop] Домен не задан; QR содержит IP компьютера.")
        try:
            self.qr_path = save_url_qr(self.url)
        except Exception as exc:
            self.report(f"[WiFiDrop] Не удалось сохранить QR: {exc}. Откройте {self.ip_url}")
            # Старое изображение не должно выглядеть как QR текущего запуска.
            with suppress(OSError):
                (PROJECT_ROOT / QR_FILENAME).unlink(missing_ok=True)
        else:
            self.report(f"[WiFiDrop] QR сохранён: {self.qr_path}")
        self.report("[WiFiDrop] Подключитесь к тому же роутеру и откройте URL или отсканируйте QR.")

    def close(self) -> None:
        if self.publisher is not None:
            self.publisher.close()
            self.publisher = None
