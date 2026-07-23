from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Account
from ..schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    LoginCodeIn,
    LoginCredentialsIn,
    LoginStageOut,
    LoginStatusOut,
    ProxyCheckOut,
)
from ..services.login_session import LOGIN_URLS, login_manager
from ..services.uploaders.base import (
    UploadError,
    normalize_storage_state,
    parse_proxy,
    proxy_egress_ip,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _save_storage_state(account_id: int, state: dict) -> str:
    """Сохраняет storage_state в файл кук аккаунта, возвращает путь."""
    import json

    settings.ensure_dirs()
    fname = f"acc{account_id}_{uuid.uuid4().hex}.json"
    path = os.path.join(settings.cookies_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return path


def _validate_proxy(proxy_url: str) -> None:
    try:
        parse_proxy(proxy_url)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _ensure_proxy_unique(db: Session, proxy_url: str, exclude_id: int | None = None) -> None:
    """Каждый аккаунт — свой прокси. Запрещаем назначить один proxy_url двум аккаунтам,
    иначе у них будет общий IP (TikTok может связать аккаунты)."""
    q = db.query(Account).filter(Account.proxy_url == proxy_url)
    if exclude_id is not None:
        q = q.filter(Account.id != exclude_id)
    other = q.first()
    if other is not None:
        raise HTTPException(
            409,
            f"Этот прокси уже привязан к аккаунту «{other.name}» (id={other.id}). "
            f"У каждого аккаунта должен быть свой прокси.",
        )


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.id.desc()).all()


@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    if payload.proxy_url:
        _validate_proxy(payload.proxy_url)
        _ensure_proxy_unique(db, payload.proxy_url)
    acc = Account(name=payload.name, platform=payload.platform, proxy_url=payload.proxy_url)
    if payload.uniqueize is not None:
        acc.uniqueize = payload.uniqueize
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    if payload.proxy_url is not None:
        if payload.proxy_url:
            _validate_proxy(payload.proxy_url)
            _ensure_proxy_unique(db, payload.proxy_url, exclude_id=acc.id)
        acc.proxy_url = payload.proxy_url or None
    if payload.name is not None:
        acc.name = payload.name
    if payload.active is not None:
        acc.active = payload.active
    if payload.uniqueize is not None:
        acc.uniqueize = payload.uniqueize
    db.commit()
    db.refresh(acc)
    return acc


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    if acc.cookies_path and os.path.exists(acc.cookies_path):
        os.remove(acc.cookies_path)
    db.delete(acc)
    db.commit()
    return {"ok": True}


@router.post("/{account_id}/cookies", response_model=AccountOut)
async def upload_cookies(account_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Загрузка кук аккаунта.

    Принимает либо Playwright storage_state (JSON вида {"cookies": [...], "origins": [...]}),
    либо массив cookies [...]. Второй вариант оборачивается в storage_state.
    """
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")

    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "Файл кук должен быть JSON (storage_state или массив cookies)")

    if isinstance(data, list) or (isinstance(data, dict) and "cookies" in data):
        # Нормализуем: чиним sameSite/expires из экспортов расширений под Playwright.
        storage_state = normalize_storage_state(data)
    else:
        raise HTTPException(400, "Не распознан формат кук. Ожидается storage_state или массив cookies.")

    settings.ensure_dirs()
    fname = f"acc{account_id}_{uuid.uuid4().hex}.json"
    path = os.path.join(settings.cookies_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f)

    # удаляем старый файл
    if acc.cookies_path and os.path.exists(acc.cookies_path):
        os.remove(acc.cookies_path)
    acc.cookies_path = path
    db.commit()
    db.refresh(acc)
    return acc


@router.post("/{account_id}/check-proxy", response_model=ProxyCheckOut)
async def check_proxy(account_id: int, db: Session = Depends(get_db)):
    """Проверяет прокси аккаунта: возвращает внешний IP, с которого виден трафик.
    Позволяет убедиться, что у каждого аккаунта свой отдельный IP."""
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not acc.proxy_url:
        return ProxyCheckOut(ok=False, ip=None, error="У аккаунта не задан прокси")

    from datetime import datetime

    ok, ip, err = False, None, None
    try:
        ip = await proxy_egress_ip(acc.proxy_url)
        ok = True
    except (UploadError, ValueError) as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001 — сетевые/прокси ошибки показываем как есть
        err = f"Прокси недоступен: {e}"
    # сохраняем результат в аккаунт (тот же статус, что показывает автопроверка)
    acc.proxy_ok = ok
    acc.proxy_ip = ip
    acc.proxy_checked_at = datetime.now()
    db.commit()
    return ProxyCheckOut(ok=ok, ip=ip, error=err)


# ---------- Встроенный вход (логин/пароль → код с почты) ----------
def _apply_saved_state(acc: Account, db: Session, state: dict) -> None:
    """Сохраняет полученный storage_state в куки аккаунта."""
    path = _save_storage_state(acc.id, state)
    if acc.cookies_path and os.path.exists(acc.cookies_path):
        os.remove(acc.cookies_path)
    acc.cookies_path = path
    db.commit()


def _stage_out(result: dict) -> LoginStageOut:
    return LoginStageOut(
        stage=result["stage"],
        screenshot=result.get("screenshot"),
        message=result.get("message"),
    )


@router.get("/login/status", response_model=LoginStatusOut)
def login_status():
    return login_manager.status()


@router.post("/login/cancel")
async def login_cancel():
    """Отменяет текущую сессию входа (закрывает браузер без сохранения кук)."""
    await login_manager.cancel()
    return {"ok": True}


@router.post("/{account_id}/login/credentials", response_model=LoginStageOut)
async def login_credentials(account_id: int, payload: LoginCredentialsIn, db: Session = Depends(get_db)):
    """Начинает вход: заполняет логин/пароль на TikTok через прокси аккаунта.
    Возвращает стадию: done | email_code | captcha | unknown."""
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    if acc.platform.value not in LOGIN_URLS:
        raise HTTPException(400, f"Вход для платформы {acc.platform.value} не поддержан")
    try:
        result = await login_manager.start_credentials(
            account_id=acc.id,
            account_name=acc.name,
            platform=acc.platform.value,
            proxy_url=acc.proxy_url,
            username=payload.username,
            password=payload.password,
        )
    except UploadError as e:
        raise HTTPException(409, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Ошибка входа: {e}")
    if result.get("storage_state") is not None:
        _apply_saved_state(acc, db, result["storage_state"])
    return _stage_out(result)


@router.post("/{account_id}/login/code", response_model=LoginStageOut)
async def login_code(account_id: int, payload: LoginCodeIn, db: Session = Depends(get_db)):
    """Отправляет код с почты. При успехе сохраняет куки и закрывает сессию."""
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    try:
        result = await login_manager.submit_code(account_id, payload.code)
    except UploadError as e:
        raise HTTPException(409, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Ошибка подтверждения кода: {e}")
    if result.get("storage_state") is not None:
        _apply_saved_state(acc, db, result["storage_state"])
    return _stage_out(result)
