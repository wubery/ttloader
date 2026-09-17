"""Автоповтор упавших задач: расписание попыток и что повторять не стоит.

Повтор планирует планировщик, а не runner: статус failed выставляется в runner
в полудюжине мест, и трогать их все ради одной политики — лишний риск. Здесь
только чистые правила, планировщик их применяет.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Пауза перед попыткой N (N считается с нуля): 5, 10, 15, 30, 60 минут.
RETRY_DELAYS_MIN = (5, 10, 15, 30, 60)
MAX_ATTEMPTS = len(RETRY_DELAYS_MIN)

# Ошибки, которые повтор заведомо не лечит: нужен человек. Протухшие куки сюда
# НЕ входят — между попытками автоперелогин может вернуть аккаунт в строй.
FATAL_MARKERS = (
    "файл видео отсутствует",
    "видео не найдено",
    "аккаунт не найден",
    "аккаунт выключен",
    "не найден бинарник",          # ffmpeg/ffprobe не установлен
)


def retry_delay(attempts: int) -> timedelta | None:
    """Через сколько повторять после `attempts` уже сделанных попыток; None — хватит."""
    if attempts < 0 or attempts >= MAX_ATTEMPTS:
        return None
    return timedelta(minutes=RETRY_DELAYS_MIN[attempts])


def is_retryable(error: str | None) -> bool:
    text = (error or "").lower()
    return not any(m in text for m in FATAL_MARKERS)


def schedule_retry(error: str | None, attempts: int, now: datetime) -> datetime | None:
    """Когда повторить упавшую задачу; None — не повторять."""
    if not is_retryable(error):
        return None
    delay = retry_delay(attempts)
    return now + delay if delay else None
