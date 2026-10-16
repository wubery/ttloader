"""Ограничение попыток входа в панель.

Без него пароль и шестизначный код из Telegram можно было перебирать без
ограничений, а через панель доступны куки и пароли всех аккаунтов. Две защиты:

* по адресу клиента — 5 неудач за 15 минут блокируют этот адрес на 15 минут;
* общая — 50 неудач за 15 минут блокируют вход для всех. Нужна потому, что за
  Cloudflare/прокси адрес клиента может быть адресом прокси или подделан
  заголовком; цена — во время атаки владелец тоже ждёт, но перебор остановлен.

Общая защита не должна запирать самого владельца: набрать 50 неудач может
кто угодно (заголовок CF-Connecting-IP подделывается), и вход закрывался для
всех. Поэтому адрес, с которого за последние 30 дней был удачный вход,
считается доверенным: на него действует только его собственный лимит.

Состояние в памяти: после перезапуска счётчики обнуляются, это допустимо —
перезапуск не даёт атакующему ничего, кроме ещё одной порции из пяти попыток.
"""
from __future__ import annotations

import threading
import time

WINDOW = 15 * 60
PER_KEY = 5
GLOBAL = 50
_GLOBAL_KEY = "*"

TRUST_TTL = 30 * 24 * 3600

_fails: dict[str, list[float]] = {}
_trusted: dict[str, float] = {}       # адрес → до какого момента доверяем
_lock = threading.Lock()


def _recent(key: str, now: float) -> list[float]:
    stamps = [t for t in _fails.get(key, []) if now - t < WINDOW]
    _fails[key] = stamps
    return stamps


def retry_after(key: str, now: float | None = None) -> int:
    """Сколько секунд ждать; 0 — можно пробовать."""
    now = now or time.time()
    with _lock:
        checks = [(key, PER_KEY)]
        if _trusted.get(key, 0) < now:          # доверенным общий лимит не помеха
            checks.append((_GLOBAL_KEY, GLOBAL))
        for k, limit in checks:
            stamps = _recent(k, now)
            if len(stamps) >= limit:
                return max(1, int(WINDOW - (now - stamps[0])))
    return 0


def fail(key: str, now: float | None = None) -> None:
    now = now or time.time()
    with _lock:
        for k in (key, _GLOBAL_KEY):
            _fails.setdefault(k, []).append(now)


def reset(key: str, now: float | None = None) -> None:
    """Удачный вход: сбрасывает счётчик адреса (общий — нет) и делает адрес
    доверенным на TRUST_TTL."""
    now = now or time.time()
    with _lock:
        _fails.pop(key, None)
        _trusted[key] = now + TRUST_TTL
        for k in [k for k, until in _trusted.items() if until < now]:
            _trusted.pop(k, None)


def client_key(request) -> str:
    """Адрес клиента.

    За Cloudflare X-Real-IP (его ставит наш nginx) — это адрес узла Cloudflare,
    общий для всех, поэтому сначала берём CF-Connecting-IP. Его можно подделать,
    если ходить в обход Cloudflare, — от этого страхует общий лимит.
    """
    h = request.headers
    return (h.get("cf-connecting-ip") or h.get("x-real-ip")
            or (request.client.host if request.client else "") or "unknown")
