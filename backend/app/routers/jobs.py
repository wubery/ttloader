from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Account, Banner, Job, JobStatus, Video
from ..services import posting
from ..schemas import JobBulkCreate, JobBulkOut, JobCreate, JobOut
from ..scheduler import submit_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    return job


@router.post("", response_model=JobOut)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(404, "Аккаунт не найден")
    if not account.has_cookies:
        raise HTTPException(400, "У аккаунта нет кук — импортируйте storage_state перед постингом")
    if db.get(Video, payload.video_id) is None:
        raise HTTPException(404, "Видео не найдено")
    if payload.banner_id is not None and db.get(Banner, payload.banner_id) is None:
        raise HTTPException(404, "Баннер не найден")

    job = Job(
        account_id=payload.account_id,
        video_id=payload.video_id,
        banner_id=payload.banner_id,
        caption=payload.caption,
        banner_x=payload.banner_x,
        banner_y=payload.banner_y,
        banner_scale=payload.banner_scale,
        # слои редактора храним JSON-строкой
        overlays=json.dumps(payload.overlays, ensure_ascii=False) if payload.overlays else None,
        scheduled_at=payload.scheduled_at,
        status=JobStatus.pending,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Если время не задано или уже наступило — запускаем немедленно
    if job.scheduled_at is None:
        submit_job(job.id)
    return job


@router.post("/bulk", response_model=JobBulkOut)
def create_jobs_bulk(payload: JobBulkCreate, db: Session = Depends(get_db)):
    """Одно видео → несколько аккаунтов, у каждого свой рендер и свой хеш."""
    try:
        jobs, skipped = posting.create_jobs(
            db,
            account_ids=payload.account_ids,
            video_id=payload.video_id,
            banner_id=payload.banner_id,
            caption=payload.caption,
            banner_x=payload.banner_x,
            banner_y=payload.banner_y,
            banner_scale=payload.banner_scale,
            overlays=payload.overlays,
            scheduled_at=payload.scheduled_at,
            spread_min=payload.spread_min_minutes,
            spread_max=payload.spread_max_minutes,
            vary_caption=payload.vary_caption,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not jobs:
        raise HTTPException(400, "Ни одной задачи не создано: " + "; ".join(skipped))
    return JobBulkOut(jobs=jobs, skipped=skipped)


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    if job.status in (JobStatus.rendering, JobStatus.uploading):
        raise HTTPException(400, "Задача уже выполняется")
    job.status = JobStatus.pending
    job.error = None
    job.scheduled_at = None
    db.commit()
    db.refresh(job)
    submit_job(job.id)
    return job


@router.get("/{job_id}/output")
def get_job_output(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None or not job.output_filename:
        raise HTTPException(404, "Готовый файл отсутствует")
    path = os.path.join(settings.output_dir, job.output_filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path)


@router.get("/{job_id}/screenshot")
def get_job_screenshot(job_id: int, db: Session = Depends(get_db)):
    """Отдаёт скриншот страницы TikTok, сохранённый при разборе публикации.

    Имя файла загрузчик пишет в лог задачи; без этого эндпоинта посмотреть его
    можно было только по SSH, и разбирать неудачную публикацию было нечем.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    names = re.findall(r"tiktok_[a-z_]+_\d+\.png", f"{job.log or ''}\n{job.error or ''}")
    if not names:
        raise HTTPException(404, "Для этой задачи скриншота нет")
    path = os.path.join(settings.output_dir, names[-1])  # последний — самый показательный
    if not os.path.exists(path):
        raise HTTPException(404, "Файл скриншота не найден")
    return FileResponse(path, media_type="image/png")


@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    if job.output_filename:
        path = os.path.join(settings.output_dir, job.output_filename)
        if os.path.exists(path):
            os.remove(path)
    db.delete(job)
    db.commit()
    return {"ok": True}
