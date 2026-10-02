"""Validate Unicode hostnames; keep the user-facing spelling in configuration."""

import ipaddress
import unicodedata

import idna


def normalize_local_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    name = unicodedata.normalize("NFC", value.strip()).lower().rstrip(".")
    try:
        ascii_name = idna.encode(name, uts46=True, std3_rules=True).decode("ascii")
    except idna.IDNAError as exc:
        raise ValueError(
            "Имя должно содержать буквы, цифры, дефисы и точки; без URL/порта"
        ) from exc
    if len(ascii_name) > 253 or all(label.isdigit() for label in ascii_name.split(".")):
        raise ValueError("Укажите доменное имя, а не IP-адрес")
    try:
        ipaddress.ip_address(ascii_name)
    except ValueError:
        return idna.decode(ascii_name)
    raise ValueError("Укажите доменное имя, а не IP-адрес")


def domain_hostname(name: str, method: str) -> str:
    ascii_name = idna.encode(name, uts46=True, std3_rules=True).decode("ascii")
    if method == "mdns":
        if not ascii_name.endswith(".local"):
            if "." in ascii_name:
                raise ValueError("Для mDNS используйте одно имя или имя.local")
            ascii_name += ".local"
        if ascii_name.count(".") != 1:
            raise ValueError("Для mDNS используйте имя.local без вложенных доменов")
    elif ascii_name.endswith(".local"):
        raise ValueError("Суффикс .local предназначен для mDNS; выберите способ mDNS")
    return ascii_name
