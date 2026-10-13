"""Резервные копии: база, куки аккаунтов и ключ шифрования одним архивом.

Всё это лежит в одном docker-томе, и потеря тома означала потерю всех
аккаунтов: куки пришлось бы снимать заново, причём через тот же прокси.
Копия делается раз в сутки и по кнопке, хранятся последние BACKUP_KEEP штук.

Видео и рендеры в архив не входят намеренно: они занимают гигабайты и
восстанавливаются заливкой, а куки и база — нет.

ВНИМАНИЕ: в архиве лежит ключ шифрования вместе с зашифрованными паролями,
то есть архив равноценен открытым паролям. Хранить его так же, как пароли.
"""
from __future__ import annotations

import os
import re
import sqlite3
import tarfile
import tempfile
from datetime import datetime

from ..config import settings

BACKUP_KEEP = 7
NAME_RE = re.compile(r"^vp-\d{8}-\d{6}\.tar\.gz$")


def backups_dir() -> str:
    path = os.path.join(settings.data_dir, "backups")
    os.makedirs(path, exist_ok=True)
    return path


def _db_path() -> str | None:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return None
    return url[len("sqlite:///"):]


def _copy_db(dst: str) -> None:
    """Согласованная копия живой базы через backup API SQLite.

    Простое копирование файла во время записи (а в WAL ещё и без -wal файла)
    даёт битую копию; backup API снимает консистентный снимок.
    """
    src_path = _db_path()
    if not src_path or not os.path.exists(src_path):
        raise RuntimeError("База SQLite не найдена — копировать нечего")
    src = sqlite3.connect(src_path, timeout=30)
    try:
        out = sqlite3.connect(dst)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def make_backup() -> str:
    """Создаёт архив и возвращает его имя. Старые сверх BACKUP_KEEP удаляет."""
    name = f"vp-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    target = os.path.join(backups_dir(), name)
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = os.path.join(tmp, "video_poster.db")
        _copy_db(db_copy)
        partial = target + ".part"
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(db_copy, arcname="video_poster.db")
            if os.path.isdir(settings.cookies_dir):
                tar.add(settings.cookies_dir, arcname="cookies")
            key = os.path.join(settings.data_dir, "secret.key")
            if os.path.exists(key):
                tar.add(key, arcname="secret.key")
        os.replace(partial, target)
    _rotate()
    return name


def _rotate() -> None:
    for old in list_backups()[BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(backups_dir(), old["name"]))
        except OSError:
            pass


def list_backups() -> list[dict]:
    """Архивы от новых к старым."""
    out = []
    for name in os.listdir(backups_dir()):
        if not NAME_RE.match(name):
            continue
        path = os.path.join(backups_dir(), name)
        out.append({"name": name, "size": os.path.getsize(path),
                    "created_at": datetime.fromtimestamp(os.path.getmtime(path)).isoformat()})
    return sorted(out, key=lambda r: r["name"], reverse=True)


def backup_path(name: str) -> str | None:
    """Путь к архиву по имени. Имя проверяется: оно приходит из запроса."""
    if not NAME_RE.match(name or ""):
        return None
    path = os.path.join(backups_dir(), name)
    return path if os.path.isfile(path) else None
