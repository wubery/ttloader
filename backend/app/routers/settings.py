"""Настройки панели: Telegram (токен/chat_id/вход) и смена пароля админа."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SettingsOut, SettingsUpdate
from ..services.appsettings import get_settings_row
from ..services.crypto import encrypt
from ..services import ratelimit
from ..services.security import hash_password, new_secret, verify_password
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
        ms_client_id=row.ms_client_id,
        allow_shared_proxy=row.allow_shared_proxy,
    )


MIN_PASSWORD_LEN = 8


def _check_password_change(payload: SettingsUpdate, row, request: Request) -> None:
    """Новый пароль — только с текущим.

    Без этого украденная сессия (она живёт 30 дней) позволяла сменить пароль и
    закрыть панель от владельца. Неверный текущий пароль считается неудачной
    попыткой входа — перебирать его здесь не легче, чем на странице входа.
    """
    if len(payload.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Пароль короче {MIN_PASSWORD_LEN} символов")
    from .auth import _guard

    key = _guard(request)
    if not verify_password(payload.current_password or "", row.admin_pass_hash):
        ratelimit.fail(key)
        raise HTTPException(403, "Текущий пароль указан неверно")


@router.post("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, request: Request, response: Response,
                    db: Session = Depends(get_db)):
    row = get_settings_row(db)
    if payload.new_password:
        _check_password_change(payload, row, request)
    if payload.tg_bot_token is not None:
        # Токен бота — полный доступ к боту, как пароль: храним зашифрованным
        row.tg_bot_token = encrypt(payload.tg_bot_token) if payload.tg_bot_token else None
    if payload.tg_chat_id is not None:
        # Может быть несколько ID — нормализуем в «id, id» (лишние пробелы/дубли убираем)
        ids = parse_chat_ids(payload.tg_chat_id)
        row.tg_chat_id = ", ".join(ids) if ids else None
    if payload.tg_login_enabled is not None:
        row.tg_login_enabled = payload.tg_login_enabled
    if payload.ms_client_id is not None:
        row.ms_client_id = payload.ms_client_id.strip() or None
    if payload.allow_shared_proxy is not None:
        row.allow_shared_proxy = payload.allow_shared_proxy
    if payload.new_password:
        row.admin_pass_hash = hash_password(payload.new_password)
        # Новый секрет подписи — все прежние сессии (в том числе украденные)
        # становятся недействительными; текущей выдаём свежую.
        row.session_secret = new_secret()
    db.commit()
    db.refresh(row)
    if payload.new_password:
        from .auth import _set_session

        _set_session(response, row.admin_user, row.session_secret, request)
    # поллер бота сам читает токен из настроек каждую итерацию — перезапуск не нужен
    return SettingsOut(
        admin_user=row.admin_user,
        tg_bot_configured=bool(row.tg_bot_token),
        tg_chat_id=row.tg_chat_id,
        tg_login_enabled=row.tg_login_enabled,
        ms_client_id=row.ms_client_id,
        allow_shared_proxy=row.allow_shared_proxy,
    )
