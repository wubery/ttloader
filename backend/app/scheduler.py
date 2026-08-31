"""Планировщик постинга.

- Задачи со scheduled_at в будущем ждут своего времени.
- Каждую минуту фоновый опрос забирает готовые к запуску pending-задачи и
  выполняет их в пуле потоков (Playwright sync API требует отдельного потока).
- Немедленный запуск (scheduled_at пустой) тоже идёт через пул потоков.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .db import SessionLocal
from .models import Account, Job, JobStatus
from .services.runner import run_job

_executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs)
_scheduler = BackgroundScheduler(timezone=settings.timezone)
_inflight: set[int] = set()
# _inflight трогают HTTP-поток (создание задач) и поток планировщика; без блокировки
# проверка и вставка не атомарны — задачу можно запустить дважды.
_inflight_lock = threading.Lock()


def submit_job(job_id: int) -> None:
    """Поставить задачу на немедленное выполнение в пуле потоков."""
    with _inflight_lock:
        if job_id in _inflight:
            return
        _inflight.add(job_id)

    def _wrapped() -> None:
        try:
            run_job(job_id)
        finally:
            with _inflight_lock:
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


def _check_proxies() -> None:
    """Периодическая проверка прокси всех активных аккаунтов: пишет egress-IP/статус,
    при провале — уведомление в Telegram (если настроен)."""
    from .services.uploaders.base import proxy_egress_ip

    db = SessionLocal()
    try:
        accounts = (
            db.query(Account)
            .filter(Account.active.is_(True), Account.proxy_url.isnot(None))
            .all()
        )
        for acc in accounts:
            ok, ip, err = False, None, None
            try:
                ip = asyncio.run(proxy_egress_ip(acc.proxy_url))
                ok = True
            except Exception as e:  # noqa: BLE001
                err = str(e)
            acc.proxy_ok = ok
            acc.proxy_ip = ip
            acc.proxy_checked_at = datetime.now()
            db.commit()
            if not ok:
                try:  # Telegram появляется на Этапе 4 — до него это no-op
                    from .services.telegram import notify
                    notify(f"⚠️ Прокси аккаунта «{acc.name}» недоступен: {err}")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        db.close()


def _check_sessions() -> None:
    """Проверяет живость кук и перелогинивает аккаунты, у которых сессия умерла.

    Проверка редкая (часы, не минуты): каждый вход — это запуск браузера и повод для
    подозрений у TikTok.
    """
    from .services import auto_login
    from .services.uploaders.base import cookies_alive

    db = SessionLocal()
    try:
        accounts = (
            db.query(Account)
            .filter(Account.active.is_(True), Account.auto_login.is_(True))
            .all()
        )
        for acc in accounts:
            if not acc.has_tt_credentials or not acc.has_cookies:
                continue
            if auto_login.is_running(acc.id):
                continue
            try:
                if cookies_alive(acc.platform.value, acc.cookies_path, acc.proxy_url):
                    continue
            except Exception:  # noqa: BLE001 — сеть/прокси мигнули: не перелогиниваемся зря
                continue
            try:
                auto_login.start(acc.id)
            except Exception:  # noqa: BLE001
                pass
    finally:
        db.close()


def start_scheduler() -> None:
    _scheduler.add_job(_poll_due_jobs, "interval", seconds=60, id="poll_due_jobs",
                       replace_existing=True, max_instances=1)
    if settings.proxy_check_minutes and settings.proxy_check_minutes > 0:
        _scheduler.add_job(_check_proxies, "interval", minutes=settings.proxy_check_minutes,
                           id="check_proxies", replace_existing=True, max_instances=1)
    if settings.session_check_hours and settings.session_check_hours > 0:
        _scheduler.add_job(_check_sessions, "interval", hours=settings.session_check_hours,
                           id="check_sessions", replace_existing=True, max_instances=1)
    _scheduler.start()


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    _executor.shutdown(wait=False, cancel_futures=True)
