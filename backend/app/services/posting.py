"""Создание задач постинга — одна точка для панели, редактора и Telegram-бота.

Раньше логика жила в роутере, а бот дублировал её у себя и, в отличие от роутера,
не ставил задачу в очередь (`telegram.py`), из-за чего пост ждал до минуты.
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Account, Banner, Job, JobStatus, Video
from . import caption as caption_service


def _skip_reason(db: Session, account_id: int) -> str | None:
    """Почему на этот аккаунт нельзя ставить задачу (None — можно)."""
    acc = db.get(Account, account_id)
    if acc is None:
        return f"аккаунт #{account_id} — не найден"
    if not acc.active:
        return f"«{acc.name}» — аккаунт выключен"
    if not acc.has_cookies:
        return f"«{acc.name}» — нет кук, импортируйте storage_state"
    return None


def create_jobs(
    db: Session,
    *,
    account_ids: list[int],
    video_id: int,
    banner_id: int | None = None,
    caption: str = "",
    banner_x: float | None = None,
    banner_y: float | None = None,
    banner_scale: float | None = None,
    overlays: list[dict] | None = None,
    scheduled_at: datetime | None = None,
    uniq_profile_id: int | None = None,
    spread_min: int = 0,
    spread_max: int = 0,
    vary_caption: bool = False,
) -> tuple[list[Job], list[str]]:
    """Создаёт по задаче на каждый аккаунт. Возвращает (задачи, причины пропусков).

    Каждая задача рендерится отдельно, поэтому у каждого аккаунта получается свой
    файл со своим хешем — переиспользовать один рендер нельзя, удаление любой из
    задач стирает выходной файл.
    """
    if not account_ids:
        raise ValueError("Не выбрано ни одного аккаунта")
    if db.get(Video, video_id) is None:
        raise ValueError("Видео не найдено")
    if banner_id is not None and db.get(Banner, banner_id) is None:
        raise ValueError("Баннер не найден")

    # порядок сохраняем, дубли убираем
    ids: list[int] = []
    for a in account_ids:
        if a not in ids:
            ids.append(a)

    lo, hi = sorted((max(0, spread_min), max(0, spread_max)))
    overlays_json = json.dumps(overlays, ensure_ascii=False) if overlays else None
    # Планировщик сравнивает scheduled_at с наивным datetime.now(), поэтому и базу
    # берём тем же now() — иначе сдвиг часовых поясов уводит время публикации.
    base = scheduled_at or datetime.now()

    jobs: list[Job] = []
    skipped: list[str] = []
    offset = 0
    for acc_id in ids:
        reason = _skip_reason(db, acc_id)
        if reason:
            skipped.append(reason)
            continue

        when: datetime | None
        if not jobs and scheduled_at is None:
            when = None                      # первый уходит сразу
        else:
            when = base + timedelta(minutes=offset)
        if hi > 0:
            offset += random.randint(lo, hi) if hi > lo else hi

        jobs.append(
            Job(
                account_id=acc_id,
                video_id=video_id,
                banner_id=banner_id,
                caption=caption_service.vary(caption, len(jobs)) if vary_caption else caption,
                banner_x=banner_x,
                banner_y=banner_y,
                banner_scale=banner_scale,
                overlays=overlays_json,
                scheduled_at=when,
                uniq_profile_id=uniq_profile_id,
                status=JobStatus.pending,
            )
        )

    if not jobs:
        return [], skipped

    # Группу отмечаем по числу реально созданных задач: если часть аккаунтов
    # отсеялась и осталась одна задача, это уже не пачка.
    if len(jobs) > 1:
        group_id = uuid.uuid4().hex[:12]
        for job in jobs:
            job.group_id = group_id

    db.add_all(jobs)
    db.commit()
    for job in jobs:
        db.refresh(job)

    # Ставим в очередь только те, чьё время уже наступило; остальные подберёт
    # планировщик (_poll_due_jobs раз в минуту).
    from ..scheduler import submit_job

    now = datetime.now()
    for job in jobs:
        if job.scheduled_at is None or job.scheduled_at <= now:
            submit_job(job.id)
    return jobs, skipped
