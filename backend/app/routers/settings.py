"""Настройки панели: Telegram (токен/chat_id/вход) и смена пароля админа."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SettingsOut, SettingsUpdate
from ..services.appsettings import get_settings_row
from ..services.security import hash_password
from ..services.telegram import parse_chat_ids

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    row = get_settings_row(db)
    return SettingsOut(
        admin_user=row.admin_user,
        tg_bot_configured=bool(row.tg_bot_token),
        tg_chat_id=row.tg_chat_id,
        tg_login_enabled=row.tg_login_enabled,
    )


@router.post("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    row = get_settings_row(db)
    if payload.tg_bot_token is not None:
        row.tg_bot_token = payload.tg_bot_token or None
    if payload.tg_chat_id is not None:
        # Может быть несколько ID — нормализуем в «id, id» (лишние пробелы/дубли убираем)
        ids = parse_chat_ids(payload.tg_chat_id)
        row.tg_chat_id = ", ".join(ids) if ids else None
    if payload.tg_login_enabled is not None:
        row.tg_login_enabled = payload.tg_login_enabled
    if payload.new_password:
        row.admin_pass_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(row)
    # поллер бота сам читает токен из настроек каждую итерацию — перезапуск не нужен
    return SettingsOut(
        admin_user=row.admin_user,
        tg_bot_configured=bool(row.tg_bot_token),
        tg_chat_id=row.tg_chat_id,
        tg_login_enabled=row.tg_login_enabled,
    )
