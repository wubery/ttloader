"""Планировщик постинга.

- Задачи со scheduled_at в будущем ждут своего времени.
- Каждую минуту фоновый опрос забирает готовые к запуску pending-задачи и
  выполняет их в пуле потоков (Playwright sync API требует отдельного потока).
- Немедленный запуск (scheduled_at пустой) тоже идёт через пул потоков.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .db import SessionLocal
from .models import Job, JobStatus
from .services.runner import run_job

_executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs)
_scheduler = BackgroundScheduler(timezone=settings.timezone)
_inflight: set[int] = set()


def submit_job(job_id: int) -> None:
    """Поставить задачу на немедленное выполнение в пуле потоков."""
    if job_id in _inflight:
        return
    _inflight.add(job_id)

    def _wrapped() -> None:
        try:
            run_job(job_id)
        finally:
            _inflight.discard(job_id)

    _executor.submit(_wrapped)


def _poll_due_jobs() -> None:
    """Раз в минуту: найти pending-задачи, у которых наступило время."""
    db = SessionLocal()
    try:
        now = datetime.now()
        jobs = (
            db.query(Job)
            .filter(Job.status == JobStatus.pending)
            .all()
        )
        for job in jobs:
            if job.id in _inflight:
                continue
            if job.scheduled_at is None or job.scheduled_at <= now:
                submit_job(job.id)
    finally:
        db.close()


def start_scheduler() -> None:
    _scheduler.add_job(_poll_due_jobs, "interval", seconds=60, id="poll_due_jobs",
                       replace_existing=True, max_instances=1)
    _scheduler.start()


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    _executor.shutdown(wait=False, cancel_futures=True)
