"""Подпись событий шины: каноническая строка + HMAC-SHA256 + окно времени.

Библиотека, а не скрипт: импортируется продюсером, консьюмером и проверками.
Каноническая строка: type \n id \n time \n sha256(canonical_json(data))
Канонический JSON: ключи отсортированы, разделитель ",", ":" без пробелов, UTF-8.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

TIME_WINDOW = timedelta(seconds=300)  # допуск |now - time| по Р3/Р5

FIELDS = ("type", "id", "time")


def canonical_json(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def canonical_string(event: dict) -> bytes:
    """Строка, которую подписываем. Порядок полей фиксирован — не менять."""
    payload_hash = hashlib.sha256(canonical_json(event.get("data", {}))).hexdigest()
    return "\n".join([event[f] for f in FIELDS] + [payload_hash]).encode("utf-8")


def sign(event: dict, key: bytes) -> str:
    """Подписать конверт события (добавляет расширение citysig)."""
    event["citysig"] = hmac.new(key, canonical_string(event), hashlib.sha256).hexdigest()
    return event["citysig"]


def verify(event: dict, key: bytes) -> bool:
    """Проверить подпись citysig. Не бросает исключений."""
    sig = event.get("citysig", "")
    if not sig:
        return False
    expected = hmac.new(key, canonical_string(event), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def parse_time(value: str) -> datetime:
    """RFC 3339 с Z → datetime в UTC. ValueError при плохом формате."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fresh(event: dict, now: datetime | None = None) -> bool:
    """Окно времени: событие не старше TIME_WINDOW и не из будущего."""
    now = now or datetime.now(timezone.utc)
    try:
        ts = parse_time(event["time"])
    except (KeyError, ValueError):
        return False
    return abs(now - ts) <= TIME_WINDOW
