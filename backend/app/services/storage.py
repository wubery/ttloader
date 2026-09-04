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
import re
import shutil
import time
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


# --- Заливка кусками ----------------------------------------------------------
# Между браузером и панелью почти всегда стоит чужой прокси (Cloudflare режет тело
# на 100 МБ, корпоративные — и того раньше), и целый ролик такой прокси отбрасывает
# ещё до бэкенда: браузер видит просто «Failed to fetch». Поэтому длинное видео
# приходит кусками по несколько мегабайт — каждый кусок это обычный маленький
# запрос, который проходит везде, а обрыв стоит одного куска, а не всей заливки.

PARTS_SUBDIR = ".parts"
UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{8,64}$")
# Брошенные куски (закрыли вкладку на середине) убираем через сутки
PARTS_TTL_SECONDS = 24 * 3600


def _parts_dir(directory: str) -> str:
    path = os.path.join(directory, PARTS_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def part_path(directory: str, upload_id: str) -> str:
    """Путь к накопительному файлу куска. Идентификатор проверяем: он приходит
    от клиента и подставляется в имя файла."""
    if not UPLOAD_ID_RE.match(upload_id or ""):
        raise HTTPException(400, "Некорректный идентификатор загрузки")
    return os.path.join(_parts_dir(directory), f"{upload_id}.part")


async def append_chunk(file: UploadFile, directory: str, upload_id: str, first: bool) -> int:
    """Дописывает кусок в накопительный файл, возвращает его текущий размер."""
    path = part_path(directory, upload_id)
    free, _ = free_space(directory)
    if free < RESERVE_BYTES:
        raise HTTPException(507, f"На диске сервера осталось {_human(free)} — заливка остановлена.")
    try:
        with open(path, "wb" if first else "ab") as f:
            while chunk := await file.read(CHUNK):
                f.write(chunk)
        return os.path.getsize(path)
    except OSError as e:
        _drop(path)
        if e.errno == 28:
            raise HTTPException(507, "Место на диске кончилось — заливка прервана.") from e
        raise HTTPException(500, f"Не удалось сохранить кусок: {e}") from e


def finish_chunks(directory: str, upload_id: str, ext: str) -> str:
    """Превращает накопленный файл в обычный файл библиотеки."""
    src = part_path(directory, upload_id)
    if not os.path.exists(src):
        raise HTTPException(404, "Загрузка не найдена — начните заново")
    fname = f"{uuid.uuid4().hex}{ext}"
    os.replace(src, os.path.join(directory, fname))
    return fname


def abort_chunks(directory: str, upload_id: str) -> None:
    _drop(part_path(directory, upload_id))


def cleanup_stale_parts(directory: str) -> int:
    """Удаляет брошенные куски. Зовётся уборщиком по расписанию."""
    path = os.path.join(directory, PARTS_SUBDIR)
    if not os.path.isdir(path):
        return 0
    removed = 0
    deadline = time.time() - PARTS_TTL_SECONDS
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) and os.path.getmtime(full) < deadline:
                os.remove(full)
                removed += 1
        except OSError:
            pass
    return removed
