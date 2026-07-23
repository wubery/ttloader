"""Аутентификация панели: логин/пароль + вход через Telegram (код)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import AuthMeOut, LoginIn, TelegramCodeIn
from ..services import telegram
from ..services.appsettings import get_settings_row
from ..services.security import sign_session, verify_password, verify_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE = "vp_session"
_MAX_AGE = 30 * 24 * 3600


def _set_session(response: Response, username: str, secret: str) -> None:
    token = sign_session(username, secret, ttl_seconds=_MAX_AGE)
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=_MAX_AGE, path="/")


@router.get("/me", response_model=AuthMeOut)
def me(request: Request, db: Session = Depends(get_db)):
    row = get_settings_row(db)
    user = verify_session(request.cookies.get(COOKIE), row.session_secret or "")
    return AuthMeOut(
        authenticated=user is not None,
        username=user,
        tg_login=bool(row.tg_bot_token and row.tg_chat_id and row.tg_login_enabled),
    )


@router.post("/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    row = get_settings_row(db)
    if payload.username != row.admin_user or not verify_password(payload.password, row.admin_pass_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    _set_session(response, row.admin_user, row.session_secret)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/telegram/request")
def telegram_request():
    if not telegram.issue_login_code():
        raise HTTPException(
            400,
            "Вход через Telegram не настроен: задайте токен бота и chat_id и включите его в «Настройках».",
        )
    return {"ok": True}


@router.post("/telegram/verify")
def telegram_verify(payload: TelegramCodeIn, response: Response, db: Session = Depends(get_db)):
    if not telegram.check_login_code(payload.code):
        raise HTTPException(401, "Неверный или просроченный код")
    row = get_settings_row(db)
    _set_session(response, row.admin_user, row.session_secret)
    return {"ok": True}
