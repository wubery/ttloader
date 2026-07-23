"""Системные операции: версия и запрос самообновления.

Обновление выполняет ХОСТОВЫЙ скрипт updater.sh (systemd/cron), а не контейнер —
панель лишь ставит флаг-файл в общий каталог /update (bind-mount). Так контейнер
не получает доступа к docker.
"""
from __future__ import annotations

import os
import time

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])

UPDATE_DIR = os.environ.get("UPDATE_DIR", "/update")


def _read(name: str, default: str = "") -> str:
    try:
        with open(os.path.join(UPDATE_DIR, name), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return default


@router.get("/version")
def version():
    return {
        "version": _read("version", "unknown"),
        "update_status": _read("status", ""),
        "update_requested": os.path.exists(os.path.join(UPDATE_DIR, "requested")),
    }


@router.post("/update")
def request_update():
    """Ставит флаг обновления; хостовый updater подхватит его и сделает git pull + rebuild."""
    if not os.path.isdir(UPDATE_DIR):
        return {"ok": False, "error": "Каталог обновления недоступен (updater не установлен)."}
    with open(os.path.join(UPDATE_DIR, "requested"), "w", encoding="utf-8") as f:
        f.write(str(int(time.time())))
    with open(os.path.join(UPDATE_DIR, "status"), "w", encoding="utf-8") as f:
        f.write("Запрошено обновление…")
    return {"ok": True}
