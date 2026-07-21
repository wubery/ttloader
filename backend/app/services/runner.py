"""Исполнение задачи постинга: рендер баннера (ffmpeg) → загрузка (Playwright).

Playwright sync API нельзя запускать внутри работающего asyncio loop, поэтому
вся работа выполняется в отдельном потоке (см. scheduler.py -> ThreadPoolExecutor).
"""
from __future__ import annotations

import os
from datetime import datetime

from ..config import settings
from ..db import SessionLocal
from ..models import Banner, BannerType, Job, JobStatus
from . import media
from .uploaders import get_uploader, parse_proxy


def _append_log(job: Job, msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    job.log = (job.log or "") + f"[{stamp}] {msg}\n"


def run_job(job_id: int) -> None:
    """Полный цикл выполнения одной задачи. Обновляет статусы прямо в БД."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        account = job.account
        video = job.video
        banner = job.banner

        video_path = os.path.join(settings.videos_dir, video.filename)
        source_path = video_path

        # 1) Наложение баннера (если задан)
        if banner is not None:
            job.status = JobStatus.rendering
            _append_log(job, "Накладываю баннер через ffmpeg…")
            db.commit()

            x = job.banner_x if job.banner_x is not None else banner.x
            y = job.banner_y if job.banner_y is not None else banner.y
            scale = job.banner_scale if job.banner_scale is not None else banner.scale
            banner_path = os.path.join(settings.banners_dir, banner.filename)
            out_name = f"job{job.id}_{int(datetime.now().timestamp())}.mp4"
            out_path = os.path.join(settings.output_dir, out_name)
            try:
                media.render_with_banner(
                    video_path=video_path,
                    banner_path=banner_path,
                    banner_is_video=(banner.type == BannerType.video),
                    output_path=out_path,
                    x=x, y=y, scale=scale, opacity=banner.opacity,
                )
            except media.MediaError as e:
                job.status = JobStatus.failed
                job.error = str(e)
                _append_log(job, f"Ошибка ffmpeg: {e}")
                db.commit()
                return
            job.output_filename = out_name
            source_path = out_path
            _append_log(job, "Баннер наложен.")
            db.commit()

        # 2) Загрузка через браузер
        job.status = JobStatus.uploading
        _append_log(job, f"Публикация в {account.platform.value}…")
        db.commit()

        proxy = parse_proxy(account.proxy_url)
        uploader = get_uploader(account.platform.value)

        def _live_log(m: str) -> None:
            # промежуточные логи не коммитим часто — копим в память загрузчика
            pass

        result = uploader(
            video_path=source_path,
            caption=job.caption or "",
            cookies_path=account.cookies_path,
            proxy=proxy,
            headless=settings.headless,
            log=_live_log,
        )
        if result.log:
            for line in result.log.splitlines():
                _append_log(job, line)

        if result.ok:
            job.status = JobStatus.done
            job.posted_url = result.url
            _append_log(job, "Задача выполнена успешно.")
        else:
            job.status = JobStatus.failed
            job.error = result.error or "Неизвестная ошибка постинга"
            _append_log(job, f"Не удалось опубликовать: {job.error}")
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.failed
            job.error = str(e)
            _append_log(job, f"Критическая ошибка: {e}")
            db.commit()
    finally:
        db.close()
