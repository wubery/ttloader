"""Приём больших файлов на диск.

Заливка длинного ролика — самая долгая операция панели, и ломается она обычно
двумя способами: кончилось место на диске или оборвался канал. И то и другое
раньше выглядело для браузера одинаково — «Failed to fetch»: сервер обрывал
соединение посреди тела запроса, а в каталоге оставался обрезанный файл, который
потом не открывался.

Поэтому: пишем во временный `.part`, переименовываем только после успешной
записи, при любой ошибке подчищаем за собой и отвечаем внятным текстом.
"""
from __future__ import annotations

import os
import shutil
import uuid

from fastapi import HTTPException, UploadFile

CHUNK = 1024 * 1024

# Сколько места оставляем свободным сверх самого файла: на рендеры (каждый —
# ещё один такой же ролик), скриншоты и базу. Меньше держать опасно: диск,
# забитый под ноль, роняет уже не заливку, а весь постинг.
RESERVE_BYTES = 512 * 1024 * 1024


def _human(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if abs(n) < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ГБ"


def free_space(path: str) -> tuple[int, int]:
    """(свободно, всего) в байтах для файловой системы каталога."""
    usage = shutil.disk_usage(path)
    return usage.free, usage.total


async def save_upload(file: UploadFile, directory: str, ext: str) -> str:
    """Сохраняет загруженный файл в каталог под случайным именем.

    Возвращает имя файла (не путь). Бросает HTTPException с понятным текстом,
    если места не хватает или запись оборвалась.
    """
    os.makedirs(directory, exist_ok=True)

    size = getattr(file, "size", None)
    free, _total = free_space(directory)
    if size and size + RESERVE_BYTES > free:
        raise HTTPException(
            507,
            f"На диске сервера не хватает места: файл {_human(size)}, "
            f"свободно {_human(free)}. Освободите место и повторите.",
        )

    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(directory, fname)
    tmp = path + ".part"
    written = 0
    try:
        with open(tmp, "wb") as f:
            while chunk := await file.read(CHUNK):
                f.write(chunk)
                written += len(chunk)
        os.replace(tmp, path)
    except OSError as e:
        _drop(tmp)
        if e.errno == 28:                     # ENOSPC
            raise HTTPException(
                507,
                f"Место на диске кончилось на {_human(written)} — файл не сохранён.",
            ) from e
        raise HTTPException(500, f"Не удалось сохранить файл: {e}") from e
    except Exception:
        # Оборванная заливка (клиент отключился) — обрезанный файл не оставляем:
        # ffprobe его не откроет, а в библиотеке он выглядел бы рабочим.
        _drop(tmp)
        raise
    return fname


def _drop(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
