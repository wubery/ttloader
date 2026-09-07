"""Планировщик постинга.

- Задачи со scheduled_at в будущем ждут своего времени.
- Каждую минуту фоновый опрос забирает готовые к запуску pending-задачи и
  выполняет их в пуле потоков (Playwright sync API требует отдельного потока).
- Немедленный запуск (scheduled_at пустой) тоже идёт через пул потоков.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .db import SessionLocal
from .models import Account, ActivityRun, Job, JobStatus
from .services.runner import run_job

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs)
_scheduler = BackgroundScheduler(timezone=settings.timezone)
_inflight: set[int] = set()
# _inflight трогают HTTP-поток (создание задач) и поток планировщика; без блокировки
# проверка и вставка не атомарны — задачу можно запустить дважды.
_inflight_lock = threading.Lock()
# Фоновая имитация не должна занимать слоты реальных публикаций, поэтому свой
# ограничитель, а не общий пул постинга.
_activity_slots = threading.Semaphore(1)
_activity_busy: set[int] = set()
# Тик частый и постоянный: диапазоны разыгрываются в БД, а не в расписании
# APScheduler — иначе смена настроек в панели требовала бы перезапуска.
ACTIVITY_TICK_SECONDS = 300


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


def _account_busy(account_id: int) -> bool:
    """Заняты ли куки аккаунта: идёт публикация, вход или другая активность.

    Два Chromium на одних куках одновременно — верный способ разлогиниться.
    """
    from .services import auto_login

    if account_id in _activity_busy:
        return True
    try:
        if auto_login.is_running(account_id):
            return True
    except Exception:  # noqa: BLE001
        pass
    db = SessionLocal()
    try:
        return db.query(Job).filter(
            Job.account_id == account_id,
            Job.status.in_([JobStatus.rendering, JobStatus.uploading]),
        ).count() > 0
    finally:
        db.close()


def _log_activity(account_id: int, kind: str, status: str, detail: str,
                  target_id: int | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(ActivityRun(account_id=account_id, kind=kind, status=status,
                           detail=(detail or "")[:2000] or None,
                           target_account_id=target_id))
        db.commit()
    finally:
        db.close()


def run_browse(account_id: int) -> None:
    """Одна сессия просмотра ленты — из тика и из кнопки «Проверить сейчас»."""
    import random as _random

    from .services import activity as act
    from .services.appsettings import get_settings_row

    if _account_busy(account_id):
        _log_activity(account_id, "browse", "skipped", "аккаунт занят публикацией или входом")
        return

    _activity_busy.add(account_id)
    try:
        with _activity_slots:
            db = SessionLocal()
            try:
                acc = db.get(Account, account_id)
                if acc is None:
                    return
                row = get_settings_row(db)
                rnd = _random.Random()
                seconds = act.session_seconds(seconds_min=row.activity_seconds_min,
                                              seconds_max=row.activity_seconds_max, rnd=rnd)
                status, detail = "ok", ""
                try:
                    detail = act.browse_feed(acc, seconds, rnd=rnd)
                except Exception as e:  # noqa: BLE001 — сессия не должна ронять планировщик
                    status, detail = "error", str(e)
                acc.last_activity_at = datetime.now()
                acc.next_activity_at = act.next_activity_time(
                    datetime.now(),
                    per_day_min=row.activity_per_day_min, per_day_max=row.activity_per_day_max,
                    hour_from=row.activity_hour_from, hour_to=row.activity_hour_to, rnd=rnd)
                name = acc.name
                db.commit()
            finally:
                db.close()
        _log_activity(account_id, "browse", status, detail)
        if status == "error":
            try:
                from .services.telegram import notify
                notify(f"\u26a0\ufe0f «{name}»: проверка активности не прошла — {detail}")
            except Exception:  # noqa: BLE001
                pass
    finally:
        _activity_busy.discard(account_id)


def run_like(liker_id: int, target_id: int) -> None:
    """Один лайк: аккаунт панели отмечает пост другого аккаунта панели."""
    from .services import activity as act

    if _account_busy(liker_id):
        _log_activity(liker_id, "like", "skipped", "аккаунт занят", target_id)
        return

    _activity_busy.add(liker_id)
    try:
        with _activity_slots:
            db = SessionLocal()
            try:
                liker, target = db.get(Account, liker_id), db.get(Account, target_id)
                if liker is None or target is None:
                    return
                # Белый список — ники ВСЕХ аккаунтов панели: барьер внутри like_one
                # сверяет с ним фактический адрес открытой страницы.
                allowed = {h for h in (act.parse_handle(a.tiktok_handle)
                                       for a in db.query(Account).all()) if h}
                try:
                    status, detail = act.like_one(liker, target.tiktok_handle, allowed)
                except Exception as e:  # noqa: BLE001
                    status, detail = "error", str(e)
            finally:
                db.close()
        _log_activity(liker_id, "like", status, detail, target_id)
    finally:
        _activity_busy.discard(liker_id)


def _recent_like_pairs(db, cooldown_hours: int) -> set[tuple[int, int]]:
    """Пары «кто кого» за окно кулдауна — в этот прогон их не берём."""
    since = datetime.now() - timedelta(hours=max(1, cooldown_hours))
    rows = db.query(ActivityRun.account_id, ActivityRun.target_account_id).filter(
        ActivityRun.kind == "like",
        ActivityRun.status == "ok",
        ActivityRun.created_at >= since,
        ActivityRun.target_account_id.isnot(None),
    ).all()
    return {(a, t) for a, t in rows}


def _activity_tick() -> None:
    """Раз в несколько минут: кому пора в ленту и пора ли раздать лайки."""
    import random as _random

    from .services import activity as act
    from .services.appsettings import get_settings_row

    db = SessionLocal()
    try:
        row = get_settings_row(db)
        accounts = db.query(Account).filter(Account.active.is_(True)).all()
        now = datetime.now()
        rnd = _random.Random()
        starts: list[tuple] = []

        if row.activity_enabled:
            due = act.due_for_activity(accounts, now)
            rnd.shuffle(due)
            starts += [("browse", a.id, None) for a in due[: max(1, row.activity_max_concurrent)]]

        if row.likes_enabled and (row.next_likes_at is None or row.next_likes_at <= now):
            lo, hi = sorted((max(0, row.likes_per_run_min), max(0, row.likes_per_run_max)))
            pairs = act.pick_like_pairs(accounts, _recent_like_pairs(db, row.like_cooldown_hours),
                                        rnd.randint(lo, hi), rnd)
            row.next_likes_at = act.next_likes_time(
                now, interval_min=row.likes_interval_min,
                interval_max=row.likes_interval_max, rnd=rnd)
            db.commit()
            starts += [("like", liker.id, target.id) for liker, target in pairs]
    finally:
        db.close()

    for kind, a_id, t_id in starts:
        target = run_browse if kind == "browse" else run_like
        args = (a_id,) if kind == "browse" else (a_id, t_id)
        threading.Thread(target=target, args=args, daemon=True).start()


def _cleanup_output() -> None:
    """Убирает старьё из output_dir — иначе каталог растёт бесконечно.

    Скриншот сохраняется на КАЖДУЮ публикацию, превью профилей остаются после
    каждого нажатия «Предпросмотр», а ретраи оставляют осиротевшие рендеры, на
    которые уже никто не ссылается. Файлы живых задач не трогаем независимо от срока.
    """
    keep_days = getattr(settings, "output_keep_days", 14)
    if not keep_days or keep_days <= 0:
        return
    cutoff = time.time() - keep_days * 86400
    out_dir = settings.output_dir
    if not os.path.isdir(out_dir):
        return

    db = SessionLocal()
    try:
        alive = {
            name for (name,) in db.query(Job.output_filename).filter(Job.output_filename.isnot(None))
        }
    finally:
        db.close()

    removed = 0
    for name in os.listdir(out_dir):
        if name in alive:
            continue                       # файл принадлежит существующей задаче
        if not (name.startswith(("tiktok_", "preview_")) or
                (name.startswith("job") and name.endswith(".mp4"))):
            continue                       # чужие файлы не наши — не трогаем
        path = os.path.join(out_dir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("Очистка output_dir: удалено файлов — %s", removed)

    # Заодно — брошенные куски незавершённых заливок (закрыли вкладку на середине).
    from .services.storage import cleanup_stale_parts

    stale = cleanup_stale_parts(settings.videos_dir)
    if stale:
        log.info("Очистка недозалитых кусков: удалено файлов — %s", stale)


def start_scheduler() -> None:
    _scheduler.add_job(_poll_due_jobs, "interval", seconds=60, id="poll_due_jobs",
                       replace_existing=True, max_instances=1)
    if settings.proxy_check_minutes and settings.proxy_check_minutes > 0:
        _scheduler.add_job(_check_proxies, "interval", minutes=settings.proxy_check_minutes,
                           id="check_proxies", replace_existing=True, max_instances=1)
    if settings.session_check_hours and settings.session_check_hours > 0:
        _scheduler.add_job(_check_sessions, "interval", hours=settings.session_check_hours,
                           id="check_sessions", replace_existing=True, max_instances=1)
    _scheduler.add_job(_cleanup_output, "interval", hours=24, id="cleanup_output",
                       replace_existing=True, max_instances=1)
    _scheduler.add_job(_activity_tick, "interval", seconds=ACTIVITY_TICK_SECONDS,
                       id="activity_tick", replace_existing=True, max_instances=1)
    _scheduler.start()


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    _executor.shutdown(wait=False, cancel_futures=True)
