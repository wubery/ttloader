"""Системные операции: версия и запрос самообновления.

Обновление выполняет ХОСТОВЫЙ скрипт updater.sh (systemd/cron), а не контейнер —
панель лишь ставит флаг-файл в общий каталог /update (bind-mount). Так контейнер
не получает доступа к docker.
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/system", tags=["system"])

UPDATE_DIR = os.environ.get("UPDATE_DIR", "/update")


def _read(name: str, default: str = "") -> str:
    try:
        with open(os.path.join(UPDATE_DIR, name), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return default


def _chown_to_dir_owner(path: str) -> None:
    """Отдать файл владельцу каталога /update.

    Контейнер пишет от root, а хостовый updater.sh обычно работает от обычного
    пользователя: без этого он не сможет ни прочитать токен, ни перезаписать статус.
    """
    try:
        st = os.stat(UPDATE_DIR)
        os.chown(path, st.st_uid, st.st_gid)
    except (OSError, AttributeError):  # не root или Windows — оставляем как есть
        pass


def _write(name: str, content: str, mode: int = 0o644) -> None:
    path = os.path.join(UPDATE_DIR, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, mode)  # файл мог существовать с другими правами
    _chown_to_dir_owner(path)


@router.get("/version")
def version():
    """Версия панели — тремя числами, чтобы обновление нельзя было принять на веру.

    `version` — что лежит в рабочем каталоге на хосте (его пишет updater.sh после
    git pull), `running` — из какого коммита собран ЗАПУЩЕННЫЙ контейнер, `behind`
    — на сколько коммитов рабочий каталог отстаёт от GitHub. Раньше отдавался
    только первый, и «Обновлено успешно» появлялось даже тогда, когда контейнер
    остался на старом коде.
    """
    on_disk = _read("version", "unknown")
    running = os.environ.get("VP_COMMIT", "unknown")
    try:
        behind = int(_read("behind", "0") or 0)
    except ValueError:
        behind = 0
    return {
        "version": on_disk,
        "running": running,
        # Код в контейнере старше того, что уже лежит на диске: нужна пересборка
        "code_stale": bool(running != "unknown" and on_disk not in ("", "unknown")
                           and running != on_disk),
        "behind": behind,
        # Отпечаток работающего апдейтера: пустой — значит процесс на хосте всё
        # ещё крутит старый код и правки в updater.sh до него не дошли
        "updater_sum": _read("updater_sum", ""),
        "update_status": _read("status", ""),
        "update_requested": os.path.exists(os.path.join(UPDATE_DIR, "requested")),
        # ok | auth_required (приватный репо без токена) | error | no_git | "" (нет апдейтера)
        "git_status": _read("git_status", ""),
    }


class GitTokenIn(BaseModel):
    token: str


@router.get("/update-log")
def update_log(lines: int = 80):
    """Последние строки журнала апдейтера.

    Без него «обновление не применилось» отлаживается только по ssh: статус в
    панели — одна строка, а причина (что подтянул git, пересобрался ли образ)
    видна лишь в логе на хосте.
    """
    path = os.path.join(UPDATE_DIR, "updater.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-max(1, min(lines, 500)):]
    except OSError:
        return {"lines": [], "detail": "Журнал недоступен — апдейтер ещё не запускался"}
    # Токен в лог не пишется, но подстраховываемся: файл отдаётся в браузер
    safe = [ln.rstrip() for ln in tail
            if "x-access-token" not in ln and "ghp_" not in ln]
    return {"lines": safe, "detail": ""}


@router.post("/git-token")
def set_git_token(payload: GitTokenIn):
    """Передаёт токен GitHub хостовому апдейтеру (для приватного репозитория).

    Токен НЕ хранится в БД: он кладётся в /update/git_token с правами 600, а
    updater.sh переносит его в git credential store и файл удаляет.
    """
    tok = payload.token.strip()
    if not tok or len(tok) > 400 or any(c.isspace() for c in tok):
        return {"ok": False, "error": "Токен выглядит некорректно (пусто или есть пробелы)."}
    if not os.path.isdir(UPDATE_DIR):
        return {"ok": False, "error": "Каталог обновления недоступен (updater не установлен)."}
    _write("git_token", tok, 0o600)
    _write("status", "Токен передан апдейтеру, применяется…")
    return {"ok": True}


@router.post("/upload-probe")
async def upload_probe(file: UploadFile = File(...)):
    """Принимает тело и возвращает его размер — ничего не сохраняет.

    Нужен, чтобы найти лимит на размер запроса ВНЕ панели: между браузером и
    сервером обычно стоит чужой прокси (Cloudflare режет тело на 100 МБ), и он
    отбрасывает запрос до бэкенда — браузер показывает просто «Failed to fetch».
    Панель шлёт сюда тела разного размера и смотрит, с какого начинается обрыв.
    """
    received = 0
    while chunk := await file.read(1024 * 1024):
        received += len(chunk)
    return {"ok": True, "received": received}


@router.post("/update")
def request_update():
    """Ставит флаг обновления; хостовый updater подхватит его и сделает git pull + rebuild."""
    if not os.path.isdir(UPDATE_DIR):
        return {"ok": False, "error": "Каталог обновления недоступен (updater не установлен)."}
    _write("requested", str(int(time.time())))
    _write("status", "Запрошено обновление…")
    return {"ok": True}
