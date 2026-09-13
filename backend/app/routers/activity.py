"""Вкладка «Активность»: диапазоны расписания, журнал и запуск вручную.

Настройки живут в той же единственной строке AppSettings, что и Telegram, —
чтобы менялись из панели и применялись сразу, без перезапуска контейнера.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, ActivityRun
from ..schemas import (
    ActivityRunOut,
    ActivitySettingsOut,
    ActivitySettingsUpdate,
    WarmupOut,
)
from ..services.appsettings import get_settings_row

router = APIRouter(prefix="/api/activity", tags=["activity"])

# Границы, за которые настройками уходить нельзя: слишком частые заходы — это
# уже не «похоже на живого человека», а нагрузка и лишний повод для подозрений.
LIMITS = {
    "activity_per_day_min": (0, 24), "activity_per_day_max": (1, 24),
    "activity_seconds_min": (10, 1800), "activity_seconds_max": (10, 1800),
    "activity_hour_from": (0, 23), "activity_hour_to": (0, 24),
    "likes_per_run_min": (0, 20), "likes_per_run_max": (0, 20),
    "likes_interval_min": (5, 1440), "likes_interval_max": (5, 1440),
    "like_cooldown_hours": (1, 720), "activity_max_concurrent": (1, 5),
    "warmup_days": (1, 60), "warmup_start_percent": (1, 100),
    "warmup_likes_after_day": (1, 60),
}


@router.get("/settings", response_model=ActivitySettingsOut)
def get_activity_settings(db: Session = Depends(get_db)):
    return get_settings_row(db)


@router.post("/settings", response_model=ActivitySettingsOut)
def update_activity_settings(payload: ActivitySettingsUpdate, db: Session = Depends(get_db)):
    row = get_settings_row(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if field in LIMITS:
            lo, hi = LIMITS[field]
            if not lo <= int(value) <= hi:
                raise HTTPException(400, f"{field}: допустимо от {lo} до {hi}")
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.get("/warmup", response_model=list[WarmupOut])
def warmup_state(db: Session = Depends(get_db)):
    """Где каждый аккаунт на шкале разгона: день, текущая доля нагрузки, лайки."""
    from datetime import datetime

    from ..services import activity as act

    row = get_settings_row(db)
    now = datetime.now()
    out = []
    for a in db.query(Account).filter(Account.active.is_(True)).all():
        started = a.warmup_started_at or a.created_at
        factor = act.warmup_factor(started, now, days=row.warmup_days,
                                   start_percent=row.warmup_start_percent,
                                   enabled=row.warmup_enabled)
        out.append(WarmupOut(
            account_id=a.id, account_name=a.name,
            day=act.warmup_day(started, now), days_total=row.warmup_days,
            percent=round(factor * 100),
            likes_allowed=act.likes_allowed(started, now,
                                            after_day=row.warmup_likes_after_day,
                                            enabled=row.warmup_enabled),
            started_at=started))
    return out


@router.post("/warmup/{account_id}/restart")
def restart_warmup(account_id: int, db: Session = Depends(get_db)):
    """Начать прогрев заново — например, после смены прокси или долгого простоя."""
    from datetime import datetime

    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    acc.warmup_started_at = datetime.now()
    db.commit()
    return {"ok": True, "detail": f"«{acc.name}»: разгон начат заново"}


@router.get("/log", response_model=list[ActivityRunOut])
def activity_log(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.query(ActivityRun).order_by(ActivityRun.id.desc()).limit(limit).all()
    names = {a.id: a.name for a in db.query(Account).all()}
    out = []
    for r in rows:
        item = ActivityRunOut.model_validate(r)
        item.account_name = names.get(r.account_id)
        item.target_name = names.get(r.target_account_id) if r.target_account_id else None
        out.append(item)
    return out


@router.post("/run/{account_id}")
def run_now(account_id: int, db: Session = Depends(get_db)):
    """«Проверить сейчас» — не дожидаясь разыгранного времени."""
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not acc.has_cookies:
        raise HTTPException(400, "Нет кук — проверять нечего")

    from ..scheduler import run_browse

    threading.Thread(target=run_browse, args=(account_id,), daemon=True).start()
    return {"ok": True, "detail": "Просмотр ленты запущен, результат появится в журнале"}
