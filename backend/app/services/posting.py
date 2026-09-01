"""Создание задач постинга — одна точка для панели, редактора и Telegram-бота.

Раньше логика жила в роутере, а бот дублировал её у себя и, в отличие от роутера,
не ставил задачу в очередь (`telegram.py`), из-за чего пост ждал до минуты.
"""
from __future__ import annotations

import json
import os
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..config import settings
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


def split_parts(duration: float, count: int) -> list[tuple[float, float]]:
    """Границы равных частей: [(начало, длительность), …].

    В сумме дают исходную длительность без нахлёстов; последняя часть добирает
    остаток от деления, чтобы не потерять хвост ролика.
    """
    if count < 2:
        raise ValueError("Частей должно быть хотя бы две")
    if duration < count * 2:
        raise ValueError(
            f"Видео слишком короткое ({duration:.0f} с) для {count} частей — "
            f"на часть остаётся меньше 2 секунд"
        )
    step = duration / count
    parts = [(round(i * step, 3), round(step, 3)) for i in range(count)]
    last_start = parts[-1][0]
    parts[-1] = (last_start, round(duration - last_start, 3))
    return parts


def create_part_jobs(
    db: Session,
    *,
    account_ids: list[int],
    video_id: int,
    parts: int,
    caption: str = "",
    caption_template: str = "Часть {n}/{total}",
    label_on: bool = True,
    banner_id: int | None = None,
    overlays: list[dict] | None = None,
    scheduled_at: datetime | None = None,
    uniq_profile_id: int | None = None,
    part_gap_min: int = 30,
    part_gap_max: int = 120,
    spread_min: int = 0,
    spread_max: int = 0,
) -> tuple[list[Job], list[str]]:
    """Режет длинное видео на части и ставит их в очередь по одной серии на аккаунт.

    На каждый аккаунт создаются ВСЕ части — чтобы серия целиком лежала в одном
    профиле. Каждая часть рендерится отдельно, поэтому уникализация у них разная.
    """
    from . import media

    video = db.get(Video, video_id)
    if video is None:
        raise ValueError("Видео не найдено")

    duration = video.duration
    if not duration:
        path = os.path.join(settings.videos_dir, video.filename)
        duration = media.probe(path).duration      # длительность не сохранилась при загрузке
    bounds = split_parts(float(duration), int(parts))

    ids: list[int] = []
    for a in account_ids:
        if a not in ids:
            ids.append(a)

    lo, hi = sorted((max(0, part_gap_min), max(0, part_gap_max)))
    acc_lo, acc_hi = sorted((max(0, spread_min), max(0, spread_max)))
    overlays_json = json.dumps(overlays, ensure_ascii=False) if overlays else None
    base = scheduled_at or datetime.now()

    jobs: list[Job] = []
    skipped: list[str] = []
    acc_offset = 0
    for acc_id in ids:
        reason = _skip_reason(db, acc_id)
        if reason:
            skipped.append(reason)
            continue

        series: list[Job] = []
        offset = acc_offset
        for idx, (start, length) in enumerate(bounds, start=1):
            label = caption_template.format(n=idx, total=len(bounds))
            when: datetime | None
            if not jobs and scheduled_at is None and idx == 1:
                when = None                       # самая первая часть уходит сразу
            else:
                when = base + timedelta(minutes=offset)

            # Подпись части — обычный текстовый слой: её рисует тот же конвейер,
            # что и слои редактора, отдельного кода в рендере не нужно.
            layers = list(overlays or [])
            if label_on:
                layers.append({
                    "type": "text", "text": label,
                    "x": 0.5, "y": 0.06, "align": "center",
                    "font_size": 0.05, "color": "#ffffff", "opacity": 1.0,
                })

            series.append(
                Job(
                    account_id=acc_id,
                    video_id=video_id,
                    banner_id=banner_id,
                    caption=f"{caption} {label}".strip() if caption else label,
                    overlays=json.dumps(layers, ensure_ascii=False) if layers else overlays_json,
                    scheduled_at=when,
                    uniq_profile_id=uniq_profile_id,
                    part_index=idx,
                    part_total=len(bounds),
                    part_start=start,
                    part_duration=length,
                    status=JobStatus.pending,
                )
            )
            if hi > 0:
                offset += random.randint(lo, hi) if hi > lo else hi

        # Группа — на серию одного аккаунта: иначе итоговое уведомление посчитает
        # части всех аккаунтов одной пачкой.
        if len(series) > 1:
            gid = uuid.uuid4().hex[:12]
            for job in series:
                job.group_id = gid
        jobs += series
        if acc_hi > 0:
            acc_offset += random.randint(acc_lo, acc_hi) if acc_hi > acc_lo else acc_hi

    if not jobs:
        return [], skipped

    db.add_all(jobs)
    db.commit()
    for job in jobs:
        db.refresh(job)

    from ..scheduler import submit_job

    now = datetime.now()
    for job in jobs:
        if job.scheduled_at is None or job.scheduled_at <= now:
            submit_job(job.id)
    return jobs, skipped
