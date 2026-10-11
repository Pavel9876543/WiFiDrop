"""Настройка одной DNS-записи через документированные API роутеров."""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.services.access_diagnostics import resolve_router_name
from app.utils.local_name import domain_hostname, normalize_local_name
from app.utils.router_url import lan_ipv4, normalize_router_url


class RouterConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RouterConnection:
    endpoint: str
    provider: str
    username: str
    password: str = field(repr=False)
    verify_tls: bool = True

    def __post_init__(self):
        object.__setattr__(self, "endpoint", normalize_router_url(self.endpoint))
        if self.provider not in {"mikrotik", "openwrt"}:
            raise RouterConfigError("Выберите API MikroTik или OpenWrt")
        if not self.username.strip():
            raise RouterConfigError("Введите логин роутера")

    @property
    def router_ip(self) -> str:
        return str(urlsplit(self.endpoint).hostname)


@dataclass(frozen=True)
class RouterCapability:
    supported: bool
    message: str


class RouterClient:
    def __init__(self, connection: RouterConnection):
        self.connection = connection
        self.http = httpx.Client(
            base_url=connection.endpoint,
            timeout=4,
            trust_env=False,
            follow_redirects=False,
            verify=connection.verify_tls,
            auth=(connection.username, connection.password)
            if connection.provider == "mikrotik"
            else None,
        )
        self.token = "0" * 32
        self.request_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.token != "0" * 32:
            with contextlib.suppress(RouterConfigError):
                self._rpc("session", "destroy", {})
        self.http.close()

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self.http.request(method, path, **kwargs)
            if response.status_code in {401, 403}:
                raise RouterConfigError("Роутер отклонил логин/пароль или права API")
            if response.status_code != 200 and response.status_code != 201:
                raise RouterConfigError(f"API роутера недоступен: HTTP {response.status_code}")
            return response.json()
        except httpx.HTTPError as exc:
            # Не выводим ответ API, URL с секретами или исходное исключение.
            raise RouterConfigError(
                "Нет соединения с API: проверьте адрес, API и сертификат"
            ) from exc
        except (ValueError, TypeError) as exc:
            if isinstance(exc, RouterConfigError):
                raise
            raise RouterConfigError("Ответ роутера не соответствует поддерживаемому API") from exc

    def _rpc(self, obj: str, method: str, args: dict) -> dict:
        self.request_id += 1
        data = self._request(
            "POST",
            "/ubus",
            json={
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": "call",
                "params": [self.token, obj, method, args],
            },
        )
        if not isinstance(data, dict) or data.get("id") != self.request_id:
            raise RouterConfigError("Неверный ответ ubus")
        result = data.get("result")
        if not isinstance(result, list) or not result or result[0] != 0:
            raise RouterConfigError(f"OpenWrt: API {obj}.{method} недоступен или недостаточно прав")
        value = result[1] if len(result) > 1 else {}
        if not isinstance(value, dict):
            raise RouterConfigError("Неверный формат ответа ubus")
        return value

    def _mikrotik_entries(self) -> list[dict]:
        entries = self._request("GET", "/rest/ip/dns/static")
        if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
            raise RouterConfigError("Неверный список DNS-записей RouterOS")
        return entries

    def _openwrt_entries(self) -> dict[str, dict]:
        entries = self._rpc("uci", "get", {"config": "dhcp"}).get("values")
        if not isinstance(entries, dict) or not all(
            isinstance(item, dict) for item in entries.values()
        ):
            raise RouterConfigError("OpenWrt не предоставляет конфигурацию DNS (dhcp)")
        return entries

    def probe(self) -> RouterCapability:
        try:
            if self.connection.provider == "mikrotik":
                resources = self._request("GET", "/rest/system/resource")
                if (
                    not isinstance(resources, list)
                    or not resources
                    or resources[0].get("platform") != "MikroTik"
                ):
                    raise RouterConfigError("Этот адрес не предоставляет API MikroTik RouterOS")
                dns_settings = self._request("GET", "/rest/ip/dns")
                if isinstance(dns_settings, list) and len(dns_settings) == 1:
                    dns_settings = dns_settings[0]
                if not isinstance(dns_settings, dict):
                    raise RouterConfigError("Неверные настройки DNS RouterOS")
                if str(dns_settings.get("allow-remote-requests")).lower() != "true":
                    raise RouterConfigError(
                        "DNS роутера не обслуживает клиентов (allow-remote-requests)"
                    )
                self._mikrotik_entries()
                # Проверяем политику текущего пользователя без пробной записи.
                users = self._request("GET", "/rest/user")
                groups = self._request("GET", "/rest/user/group")
                group = next(
                    (u.get("group") for u in users if u.get("name") == self.connection.username),
                    None,
                )
                policy = next((g.get("policy", "") for g in groups if g.get("name") == group), "")
                if "write" not in str(policy).split(","):
                    raise RouterConfigError("Не подтверждены права записи DNS (политика write)")
                return RouterCapability(True, "MikroTik: DNS API доступен, права записи проверены")
            if self.token == "0" * 32:
                login = self._rpc(
                    "session",
                    "login",
                    {
                        "username": self.connection.username,
                        "password": self.connection.password,
                        "timeout": 120,
                    },
                )
                token = login.get("ubus_rpc_session", "")
                if not re.fullmatch("[0-9a-f]{32}", token) or token == "0" * 32:
                    raise RouterConfigError("OpenWrt не предоставил сессию API")
                self.token = token
            board = self._rpc("system", "board", {})
            if "OpenWrt" not in str(board.get("release", {}).get("distribution", "")):
                raise RouterConfigError("Этот адрес не предоставляет API OpenWrt")
            entries = self._openwrt_entries()
            if not any(
                e.get(".type") == "dnsmasq" and str(e.get("port", "53")) == "53"
                for e in entries.values()
            ):
                raise RouterConfigError("OpenWrt: обслуживающий DNS dnsmasq не найден")
            permissions = [("uci", "dhcp", "write")] + [
                ("ubus", "uci", method)
                for method in ("get", "add", "set", "apply", "confirm", "rollback")
            ]
            for scope, obj, function in permissions:
                permission = self._rpc(
                    "session",
                    "access",
                    {
                        "scope": scope,
                        "object": obj,
                        "function": function,
                    },
                )
                if permission.get("access") is not True:
                    raise RouterConfigError(
                        f"OpenWrt: не подтверждены права {scope}/{obj}/{function}"
                    )
            return RouterCapability(True, "OpenWrt: DNS API доступен, права записи проверены")
        except (RouterConfigError, TypeError, AttributeError) as exc:
            message = (
                str(exc) if isinstance(exc, RouterConfigError) else "Неподдерживаемый ответ API"
            )
            return RouterCapability(False, message)

    def configure_dns(self, name: str, computer_ip: str) -> str:
        normalized = normalize_local_name(name)
        if not normalized:
            raise RouterConfigError("Введите имя сайта")
        hostname = domain_hostname(normalized, "router_dns")
        ip = lan_ipv4(computer_ip)
        # Проверка повторяется в той же сессии, в которой выполняется запись.
        capability = self.probe()
        if not capability.supported:
            raise RouterConfigError(capability.message)
        if self.connection.provider == "mikrotik":
            self._configure_mikrotik(hostname, ip)
            self._verify_dns(hostname, ip)
        else:
            self._configure_openwrt(hostname, ip)
        return (
            f"DNS роутера: {hostname} → {ip}, ответ проверен. "
            "На телефоне должен использоваться DNS этого роутера. Закрепите IP компьютера."
        )

    def _verify_dns(self, hostname: str, ip: str) -> None:
        deadline = time.monotonic() + 8
        while True:
            try:
                if resolve_router_name(hostname, self.connection.router_ip) == {ip}:
                    return
            except ValueError:
                pass
            if time.monotonic() >= deadline:
                raise RouterConfigError("Запись отправлена, но DNS роутера не подтвердил нужный IP")
            time.sleep(0.25)

    def _configure_mikrotik(self, hostname: str, ip: str) -> None:
        matches = [
            entry
            for entry in self._mikrotik_entries()
            if str(entry.get("name", "")).lower().rstrip(".") == hostname
        ]
        for entry in matches:
            if entry.get("comment") != "WiFiDrop":
                if (
                    len(matches) == 1
                    and entry.get("address") == ip
                    and entry.get("disabled", "false") == "false"
                    and entry.get("type", "A") == "A"
                ):
                    return
                raise RouterConfigError("Имя занято чужой DNS-записью; выберите другое имя")
        if len(matches) > 1:
            raise RouterConfigError(
                "Найдены несколько записей этого имени; устраните конфликт на роутере"
            )
        values = {
            "name": hostname,
            "address": ip,
            "type": "A",
            "comment": "WiFiDrop",
            "disabled": "false",
        }
        if matches:
            identity = matches[0].get(".id", "")
            if not re.fullmatch(r"\*[0-9A-Fa-f]+", identity):
                raise RouterConfigError("Неверный идентификатор DNS-записи")
            self._request("PATCH", "/rest/ip/dns/static/" + quote(identity, safe=""), json=values)
        else:
            self._request("PUT", "/rest/ip/dns/static", json=values)

    def _configure_openwrt(self, hostname: str, ip: str) -> None:
        entries = self._openwrt_entries()
        section = "wifidrop_" + hashlib.sha256(hostname.encode()).hexdigest()[:16]
        own = entries.get(section)
        if own and (own.get(".type") != "domain" or own.get("wifidrop_owner") != "1"):
            raise RouterConfigError("Раздел WiFiDrop занят чужой конфигурацией")
        for key, entry in entries.items():
            if (
                key != section
                and entry.get(".type") == "domain"
                and str(entry.get("name", "")).lower().rstrip(".") == hostname
            ):
                if entry.get("ip") == ip and not own:
                    self._verify_dns(hostname, ip)
                    return
                raise RouterConfigError("Имя занято чужой DNS-записью; выберите другое имя")
        values = {"name": hostname, "ip": ip, "wifidrop_owner": "1"}
        if own:
            self._rpc("uci", "set", {"config": "dhcp", "section": section, "values": values})
        else:
            self._rpc(
                "uci",
                "add",
                {
                    "config": "dhcp",
                    "type": "domain",
                    "name": section,
                    "values": values,
                },
            )
        # Отдельная свежая ubus-сессия содержит только нашу правку dhcp.
        # apply сам сохраняет изменения и перезапускает DNS; commit до apply не нужен.
        try:
            self._rpc("uci", "apply", {"rollback": True, "timeout": 30})
            self._verify_dns(hostname, ip)
            self._rpc("uci", "confirm", {})
        except RouterConfigError as exc:
            with contextlib.suppress(RouterConfigError):
                self._rpc("uci", "rollback", {})
            raise RouterConfigError(
                "DNS не подтверждён; запрошен откат OpenWrt (таймер 30 с)"
            ) from exc


def probe_router(connection: RouterConnection) -> RouterCapability:
    with RouterClient(connection) as client:
        return client.probe()


def configure_router_dns(connection: RouterConnection, name: str, ip: str) -> str:
    with RouterClient(connection) as client:
        return client.configure_dns(name, ip)
