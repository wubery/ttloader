"""Обратимое шифрование секретов аккаунтов (пароли TikTok/почты, refresh-токены).

В проекте уже есть security.py, но там односторонние вещи: PBKDF2 для пароля панели и
HMAC-подпись сессии. Пароль аккаунта нужно уметь прочитать обратно — браузер вводит его
в форму, поэтому здесь симметричный Fernet.

Ключ берём из переменной окружения VP_SECRET_KEY; если её нет — генерируем файл
secret.key в каталоге данных (он в docker-томе и переживает обновления). Ключ намеренно
лежит НЕ в БД: иначе он оказался бы рядом с шифротекстом и не давал бы ничего.

Границы честно: куки аккаунтов (/data/cookies/*.json) и так лежат открытым текстом —
шифрование закрывает пароли, которые человек переиспользует в других сервисах.
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"          # метка формата: по ней отличаем шифротекст от старых данных
_KEY_FILE = "secret.key"
_fernet: Fernet | None = None


def _key() -> bytes:
    """Ключ шифрования: из env или из файла в каталоге данных (создаётся один раз)."""
    env = (os.environ.get("VP_SECRET_KEY") or "").strip()
    if env:
        return env.encode()

    path = os.path.join(settings.data_dir, _KEY_FILE)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()

    settings.ensure_dirs()
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    log.info("Создан ключ шифрования секретов: %s", path)
    return key


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def encrypt(value: str | None) -> str | None:
    """Шифрует строку. Пустое значение остаётся пустым (нечего прятать)."""
    if not value:
        return None
    return PREFIX + _cipher().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """Расшифровывает строку. Возвращает None, если значение битое или не наше.

    Не бросает исключений: сменившийся ключ не должен ронять панель — пользователь
    просто увидит, что пароль надо ввести заново.
    """
    if not value:
        return None
    if not value.startswith(PREFIX):
        # данные, записанные до появления шифрования, читаем как есть
        return value
    try:
        return _cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        log.warning("Не удалось расшифровать секрет — вероятно, сменился ключ VP_SECRET_KEY")
        return None
