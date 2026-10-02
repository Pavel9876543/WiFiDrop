from __future__ import annotations

import idna


def normalize_local_name(value: str | None) -> str | None:
    """Нормализует локальное DNS-имя; кириллица хранится в читаемом виде."""
    if value is None or not value.strip():
        return None
    name = value.strip().lower().rstrip(".")
    if not name:
        raise ValueError("Введите имя без URL и порта")
    try:
        ascii_name = idna.encode(name, uts46=True).decode("ascii")
        name = idna.decode(ascii_name)
    except idna.IDNAError as exc:
        raise ValueError(
            "Некорректное локальное имя: буквы, цифры и дефис; до 63 байт IDNA"
        ) from exc
    if ascii_name.isdigit():
        raise ValueError("Локальное имя не должно состоять только из цифр")
    return name


def local_hostname(name: str, mode: str = "mdns") -> str:
    hostname = idna.encode(name, uts46=True).decode("ascii")
    return hostname + ".local" if mode == "mdns" else hostname
