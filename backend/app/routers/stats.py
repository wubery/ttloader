"""Архив статистики: исходы задач, которые уже удалены из очереди.

Выполненные задачи чистятся через несколько дней, а цифры должны жить дальше.
Панель считает статистику как «живые задачи + этот счётчик».
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import JobStat
from ..schemas import JobStatOut

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/archive", response_model=list[JobStatOut])
def archive(db: Session = Depends(get_db)):
    return db.query(JobStat).order_by(JobStat.day.desc()).all()
