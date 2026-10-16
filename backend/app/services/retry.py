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


# Маркер, который загрузчик пишет в лог прямо перед нажатием «Опубликовать».
PUBLISH_MARKER = "Публикую…"
# Начало новой попытки: автоповтор пишет первую строку, ручной перезапуск — вторую.
# Без второй старая метка «Публикую…» оставалась в хвосте, и после ручного
# перезапуска любая ранняя ошибка (прокси, куки) навсегда отключала автоповтор.
MANUAL_RETRY_MARKER = "Перезапуск вручную."
_ATTEMPT_MARKERS = ("Автоповтор ", MANUAL_RETRY_MARKER)


def publish_attempted(log: str | None) -> bool:
    """Дошла ли ПОСЛЕДНЯЯ попытка до нажатия «Опубликовать».

    Если да, повторять автоматически нельзя: TikTok мог принять ролик, а
    панель — не дождаться подтверждения, и повтор выложит дубль. Смотрим
    только хвост лога после начала последней попытки — прошлые не в счёт.
    """
    text = log or ""
    cut = max(text.rfind(m) for m in _ATTEMPT_MARKERS)
    tail = text[cut:] if cut >= 0 else text
    return PUBLISH_MARKER in tail


def schedule_retry_for(error: str | None, log: str | None, attempts: int,
                       now: datetime) -> tuple[datetime | None, str]:
    """Как schedule_retry, но с причиной отказа для лога задачи."""
    if publish_attempted(log):
        return None, ("Повтор не планируется: публикация могла пройти — проверьте "
                      "профиль и, если ролика нет, перезапустите вручную.")
    if not is_retryable(error):
        return None, "Повтор не планируется: ошибка требует вмешательства."
    when = schedule_retry(error, attempts, now)
    return when, ""
