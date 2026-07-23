"""Доступ к единственной строке настроек панели и её первичная инициализация."""
from __future__ import annotations

import os
import secrets

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AppSettings
from .security import hash_password, new_secret


def get_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def bootstrap_settings() -> None:
    """Гарантирует строку настроек: секрет сессии + админ-креды.

    Логин/пароль берутся из env ADMIN_USER/ADMIN_PASS при первом запуске
    (их задаёт install.sh). Если пароль не задан и ещё не установлен — генерируем
    случайный и печатаем в лог контейнера (docker compose logs backend)."""
    db = SessionLocal()
    try:
        row = get_settings_row(db)
        if not row.session_secret:
            row.session_secret = new_secret()
        env_user = os.environ.get("ADMIN_USER")
        if env_user:
            row.admin_user = env_user
        if not row.admin_pass_hash:
            env_pass = os.environ.get("ADMIN_PASS")
            if env_pass:
                row.admin_pass_hash = hash_password(env_pass)
            else:
                pw = secrets.token_urlsafe(12)
                row.admin_pass_hash = hash_password(pw)
                print(f"[appsettings] Сгенерирован пароль администратора: {pw}", flush=True)
                print("[appsettings] Логин: " + row.admin_user, flush=True)
        db.commit()
    finally:
        db.close()
