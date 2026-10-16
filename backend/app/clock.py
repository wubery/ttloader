"""Единые часы панели: «сейчас» и все хранимые даты — в поясе TIMEZONE.

Раньше время жило в трёх поясах сразу. Панель присылала запланированное время
в UTC, бэкенд отбрасывал пояс и сравнивал результат с datetime.now() сервера, а
created_at/updated_at писал SQLite (CURRENT_TIMESTAMP — всегда UTC). Наружу
время уходило без пояса, и браузер читал его как своё местное. Итог: пост,
запланированный через 30 минут, на сервере с UTC+3 уходил сразу; в очереди время
показывалось на 3 часа раньше выбранного, окно активности «9–23» означало
12–02 по Москве.

Правило теперь одно: в БД и в коде — наивное время в поясе TIMEZONE
(clock.now()); на входе API время с поясом переводится в него, на выходе к нему
дописывается пояс. От часового пояса самого сервера или контейнера не зависит
ничего.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings

log = logging.getLogger(__name__)


def zone(name: str | None) -> tzinfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Неизвестный часовой пояс %r — считаю время в UTC", name)
        return timezone.utc


TZ = zone(settings.timezone)


def now() -> datetime:
    """Текущее время в поясе панели, без tzinfo — в таком виде оно хранится в БД."""
    return datetime.now(TZ).replace(tzinfo=None)


def to_local(dt: datetime | None) -> datetime | None:
    """Время с поясом → наивное в поясе панели. Наивное считается уже местным."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(TZ).replace(tzinfo=None)


def to_aware(dt: datetime | None) -> datetime | None:
    """Наивное время панели → с поясом (для выдачи наружу и сравнения с чужим)."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=TZ)


def convert(dt: datetime, src: tzinfo, dst: tzinfo) -> datetime:
    """Наивное время из пояса src → наивное в поясе dst."""
    return dt.replace(tzinfo=src).astimezone(dst).replace(tzinfo=None)


# --------------------------------------------------------------- перевод данных

# Колонки, которые до перехода заполнял SQLite (CURRENT_TIMESTAMP) — они в UTC.
_UTC_COLUMNS = {"created_at", "updated_at"}
# scheduled_at в основном приходил из панели (toISOString) — тоже UTC.
_UTC_LEGACY = _UTC_COLUMNS | {"scheduled_at"}


def _system_zone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def migrate_stored_times() -> int:
    """Один раз переводит уже сохранённые даты в пояс панели.

    В AppSettings.clock_tz помнится, в каком поясе лежат данные. Пусто — данные
    старого формата: created_at/updated_at/scheduled_at в UTC, прочее — в поясе
    сервера. Если TIMEZONE потом сменят, всё переводится из прежнего пояса в
    новый. Возвращает число изменённых строк.
    """
    from sqlalchemy import DateTime, and_, select

    from .db import Base, SessionLocal, engine
    from .services.appsettings import get_settings_row

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        stored = row.clock_tz
        target = settings.timezone
        if stored == target:
            return 0
    finally:
        db.close()

    dst = TZ
    legacy = stored is None
    old = None if legacy else zone(stored)
    system = _system_zone()

    def source(col: str) -> tzinfo:
        if not legacy:
            return old
        return timezone.utc if col in _UTC_LEGACY else system

    changed = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            cols = [c for c in table.columns if isinstance(c.type, DateTime)]
            pk = list(table.primary_key.columns)
            if not cols or not pk:
                continue
            try:
                rows = conn.execute(select(*pk, *cols)).all()
            except Exception as e:  # noqa: BLE001 — битая строка не должна ронять старт
                log.warning("Даты таблицы %s не переведены: %s", table.name, e)
                continue
            for r in rows:
                m = r._mapping
                # Все колонки времени — в values, даже неизменные: иначе Core
                # подставит onupdate и перезапишет updated_at текущим временем.
                values = {c.name: (convert(m[c], source(c.name), dst) if m[c] is not None else None)
                          for c in cols}
                if all(values[c.name] == m[c] for c in cols):
                    continue
                conn.execute(table.update()
                             .where(and_(*(p == m[p] for p in pk)))
                             .values(**values))
                changed += 1

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        row.clock_tz = target
        db.commit()
    finally:
        db.close()
    if changed:
        log.info("Даты переведены в пояс %s: строк — %s", target, changed)
    return changed
