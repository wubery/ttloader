from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Account, Banner, Job, JobStatus, Video
from ..schemas import JobCreate, JobOut
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
