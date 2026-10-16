"""Удаление видео, баннеров и задач — одно правило для панели и Telegram-бота.

Раньше бот удалял по-своему: стирал файл ролика ДО записи в БД, запись падала
на NOT NULL у jobs.video_id, ошибка молча глоталась — и ролик оставался в
библиотеке без файла, а все его задачи падали. Удаление баннера молча снимало
его с ещё не выполненных задач, и они уходили без баннера.

Порядок везде один: проверки → БД (commit) → файлы. Файл стираем только когда
запись уже удалена: потерянный файл без записи — мусор на диске, а запись без
файла — сломанные задачи.
"""
from __future__ import annotations

import json
import os

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Banner, Job, JobStatus, Video

RUNNING = (JobStatus.rendering, JobStatus.uploading)


class DeleteBlocked(Exception):
    """Удалять нельзя. needs_force — можно, но с явным подтверждением (в API это
    409, на который панель переспрашивает); иначе — нельзя совсем (400)."""

    def __init__(self, message: str, *, needs_force: bool = False):
        super().__init__(message)
        self.needs_force = needs_force


def _remove_file(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _drop_job(db: Session, job: Job) -> None:
    from ..scheduler import archive_job

    archive_job(db, job)          # исход — в счётчик, рендер и скриншоты — с диска
    db.delete(job)


def drop_job(db: Session, job: Job) -> None:
    """Удаляет задачу без commit (для удаления вместе с владельцем)."""
    if job.status in RUNNING:
        raise DeleteBlocked("Задача сейчас выполняется — дождитесь окончания.")
    _drop_job(db, job)


def delete_job(db: Session, job: Job) -> None:
    drop_job(db, job)
    db.commit()


def delete_video(db: Session, video: Video, *, force: bool = False) -> int:
    """Удаляет ролик; с задачами — только по force. Возвращает число удалённых задач."""
    jobs = db.query(Job).filter(Job.video_id == video.id).all()
    if any(j.status in RUNNING for j in jobs):
        raise DeleteBlocked("По этому видео сейчас идёт публикация — дождитесь окончания.")
    if jobs and not force:
        raise DeleteBlocked(
            f"На это видео завязано задач: {len(jobs)}. "
            f"Удаление сотрёт их вместе с историей публикаций.",
            needs_force=True,
        )
    for job in jobs:
        _drop_job(db, job)
    path = os.path.join(settings.videos_dir, video.filename)
    db.delete(video)
    db.commit()
    _remove_file(path)
    return len(jobs)


def _uses_banner(job: Job, banner_id: int) -> bool:
    if job.banner_id == banner_id:
        return True
    try:
        layers = json.loads(job.overlays) if job.overlays else []
    except (TypeError, ValueError):
        return False
    return isinstance(layers, list) and any(
        isinstance(it, dict) and it.get("banner_id") == banner_id for it in layers)


def banner_users(db: Session, banner_id: int) -> tuple[list[Job], list[Job]]:
    """(невыполненные, выполняющиеся) задачи, в которых участвует баннер."""
    open_jobs = db.query(Job).filter(Job.status.in_((JobStatus.pending, *RUNNING))).all()
    users = [j for j in open_jobs if _uses_banner(j, banner_id)]
    return ([j for j in users if j.status == JobStatus.pending],
            [j for j in users if j.status in RUNNING])


def delete_banner(db: Session, banner: Banner, *, force: bool = False) -> int:
    """Удаляет баннер. Если его ждут запланированные задачи — только по force:
    тогда они уйдут без баннера. Возвращает число таких задач."""
    pending, running = banner_users(db, banner.id)
    if running:
        raise DeleteBlocked("Баннер сейчас вжигается в ролик — дождитесь окончания.")
    if pending and not force:
        raise DeleteBlocked(
            f"Баннер стоит в запланированных задачах: {len(pending)}. "
            f"Если удалить, они выйдут без него.",
            needs_force=True,
        )
    path = os.path.join(settings.banners_dir, banner.filename)
    db.delete(banner)             # у выполненных задач banner_id станет пустым — это история
    db.commit()
    _remove_file(path)
    return len(pending)
