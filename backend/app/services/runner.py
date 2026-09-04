"""Исполнение задачи постинга: рендер баннера (ffmpeg) → загрузка (Playwright).

Playwright sync API нельзя запускать внутри работающего asyncio loop, поэтому
вся работа выполняется в отдельном потоке (см. scheduler.py -> ThreadPoolExecutor).
"""
from __future__ import annotations

import json
import random
import os
import time
from datetime import datetime

from ..config import settings
from ..db import SessionLocal
from ..models import Banner, BannerType, Job, JobStatus
from . import media, uniqueizer
from .uploaders import get_uploader, parse_proxy
from .uploaders.base import UploadError


def _append_log(job: Job, msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    job.log = (job.log or "") + f"[{stamp}] {msg}\n"


def _ensure_session(account, db, log) -> bool:
    """Проверяет куки и при необходимости выполняет автоматический вход.

    True — можно постить (сессия жива или её восстановили), False — нет.
    """
    from .auto_login import get_state, is_running, start
    from .uploaders.base import cookies_alive

    try:
        if cookies_alive(account.platform.value, account.cookies_path, account.proxy_url):
            return True
    except Exception as e:  # noqa: BLE001 — сеть мигнула: пробуем постить как есть
        log(f"Не удалось проверить сессию ({e}) — продолжаю с текущими куками.")
        return True

    if not account.has_tt_credentials or not account.auto_login:
        log("Куки аккаунта недействительны, а данных для входа нет.")
        return False

    log("Куки протухли — вхожу в аккаунт заново…")
    if not is_running(account.id):
        start(account.id)

    waited = 0
    while waited < 420:      # вход с ожиданием письма занимает минуты
        time.sleep(5)
        waited += 5
        state = get_state(account.id)
        if state.get("stage") == "done":
            db.refresh(account)
            log("Вход выполнен, продолжаю публикацию.")
            return True
        if state.get("stage") in ("error", "captcha"):
            log(f"Войти не удалось: {state.get('message')}")
            return False
    log("Вход не завершился за 7 минут.")
    return False


def _resolve_profile(job: Job, account, db):
    """Профиль задачи → профиль аккаунта → профиль по умолчанию → None.

    None означает «работает старое поведение по флагу Account.uniqueize».
    """
    from ..models import UniqProfile

    for pid in (getattr(job, "uniq_profile_id", None), getattr(account, "uniq_profile_id", None)):
        if pid:
            row = db.get(UniqProfile, pid)
            if row is not None:
                return row
    if not bool(getattr(account, "uniqueize", True)):
        return None      # уникализация у аккаунта выключена — профиль по умолчанию не навязываем
    return db.query(UniqProfile).filter(UniqProfile.is_default.is_(True)).first()


def _pick_assets(params: dict, db, group_id: int | None = None
                 ) -> tuple[str | None, str | None, str | None, bool, str | None]:
    """Выбирает файлы хука, оверлея, фона и рекламы по настройкам профиля.

    group_id — группа аккаунта, на который идёт публикация. Случайный выбор хука
    и фона сужается до файлов, доступных этой группе (см. services/folders.py);
    у оверлеев и рекламы папок нет, они берутся из всей библиотеки. Явно
    указанный в профиле файл (asset_id) берётся как есть: это осознанная
    настройка, молча подменять её не на что.
    """
    from ..models import AdClip, Background, Hook, OverlayAsset
    from . import folders

    hook_path = None
    hook_cfg = params.get("hook") or {}
    if hook_cfg.get("on"):
        row = db.get(Hook, hook_cfg["asset_id"]) if hook_cfg.get("asset_id") else None
        if row is None and hook_cfg.get("random", True):
            rows = folders.visible_rows(db, Hook, "hook", group_id)
            row = random.choice(rows) if rows else None
        if row is not None:
            path = os.path.join(settings.hooks_dir, row.filename)
            hook_path = path if os.path.exists(path) else None

    overlay_png = None
    ov_cfg = params.get("overlay") or {}
    if ov_cfg.get("on"):
        row = db.get(OverlayAsset, ov_cfg["asset_id"]) if ov_cfg.get("asset_id") else None
        if row is None and ov_cfg.get("random", True):
            rows = db.query(OverlayAsset).all()
            row = random.choice(rows) if rows else None
        if row is not None:
            path = os.path.join(settings.overlays_dir, row.filename)
            overlay_png = path if os.path.exists(path) else None

    background = None
    bg_is_video = False
    canvas_cfg = params.get("canvas") or {}
    if canvas_cfg.get("bg") == "image":
        row = db.get(Background, canvas_cfg["bg_asset_id"]) if canvas_cfg.get("bg_asset_id") else None
        if row is None and canvas_cfg.get("bg_random", True):
            rows = folders.visible_rows(db, Background, "background", group_id)
            row = random.choice(rows) if rows else None
        if row is not None:
            path = os.path.join(settings.backgrounds_dir, row.filename)
            if os.path.exists(path):
                background, bg_is_video = path, bool(row.is_video)

    ad_path = None
    ad_cfg = params.get("ad") or {}
    if ad_cfg.get("on"):
        row = db.get(AdClip, ad_cfg["asset_id"]) if ad_cfg.get("asset_id") else None
        if row is None and ad_cfg.get("random", True):
            rows = db.query(AdClip).all()
            row = random.choice(rows) if rows else None
        if row is not None:
            path = os.path.join(settings.ads_dir, row.filename)
            ad_path = path if os.path.exists(path) else None

    return hook_path, overlay_png, background, bg_is_video, ad_path


def _banner_layer(job: Job, banner) -> list[dict]:
    """Одиночный баннер задачи в виде слоя для конвейера.

    Ветка профиля рендерит всё одним проходом и знает только про слои редактора,
    поэтому баннер, выбранный в «Новом посте» (job.banner_id), надо превратить в
    такой же слой — иначе он не вжигается вовсе.
    """
    if banner is None:
        return []
    return [{
        "type": "banner",
        "path": os.path.join(settings.banners_dir, banner.filename),
        "is_video": banner.type == BannerType.video,
        # переопределения задачи приоритетнее сохранённых у баннера
        "x": job.banner_x if job.banner_x is not None else banner.x,
        "y": job.banner_y if job.banner_y is not None else banner.y,
        "scale": job.banner_scale if job.banner_scale is not None else banner.scale,
        "opacity": banner.opacity,
        "motion": getattr(banner, "motion", "none") or "none",
        "motion_speed": getattr(banner, "motion_speed", 1.0) or 1.0,
    }]


def _live_log_render(job: Job, db):
    """Пишет строки конвейера в лог задачи — видно, какие параметры разыгрались."""

    def _log(msg: str) -> None:
        try:
            _append_log(job, msg)
            db.commit()
        except Exception:  # noqa: BLE001 — лог не должен ронять рендер
            db.rollback()

    return _log


def _notify_result(db, job: Job, account, *, ok: bool) -> None:
    """Уведомление в Telegram (no-op, если бот не настроен).

    Для пачки (одно видео на несколько аккаунтов) успехи по отдельности не шлём —
    иначе десять аккаунтов дают десять сообщений. Вместо этого одно итоговое,
    когда в группе не осталось незавершённых задач. Ошибки шлём сразу.
    """
    try:
        from .telegram import notify

        if not ok:
            notify(f"❌ Пост не удался: {account.name} — задача #{job.id}\n{job.error}")
        elif not job.group_id:
            notify(f"✅ Пост опубликован: {account.name} [{account.platform.value}] — задача #{job.id}")

        if not job.group_id:
            return
        rows = db.query(Job).filter(Job.group_id == job.group_id).all()
        if any(j.status in (JobStatus.pending, JobStatus.rendering, JobStatus.uploading) for j in rows):
            return
        done = sum(1 for j in rows if j.status == JobStatus.done)
        failed = sum(1 for j in rows if j.status == JobStatus.failed)
        notify(
            f"📦 Пачка завершена: опубликовано {done} из {len(rows)}"
            + (f", ошибок {failed}" if failed else "")
        )
    except Exception:  # noqa: BLE001
        pass


def _parse_overlays(job: Job, db) -> list[dict]:
    """Разбирает job.overlays (JSON от редактора) в список слоёв для ffmpeg.

    Фронт присылает баннеры по banner_id — здесь подставляем реальные пути к файлам
    и тип (картинка/видео). Некорректные слои молча пропускаем."""
    raw = getattr(job, "overlays", None)
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []

    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        kind = (it.get("type") or "banner").lower()
        if kind == "text":
            out.append(it)
            continue
        b = db.get(Banner, it.get("banner_id")) if it.get("banner_id") else None
        if b is None:
            continue
        layer = dict(it)
        layer["type"] = "banner"
        layer["path"] = os.path.join(settings.banners_dir, b.filename)
        layer["is_video"] = (b.type == BannerType.video)
        # если фронт не передал параметры — берём сохранённые у баннера
        layer.setdefault("x", b.x)
        layer.setdefault("y", b.y)
        layer.setdefault("scale", b.scale)
        layer.setdefault("opacity", b.opacity)
        layer.setdefault("motion", getattr(b, "motion", "none") or "none")
        layer.setdefault("motion_speed", getattr(b, "motion_speed", 1.0) or 1.0)
        out.append(layer)
    return out


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

        # 0) Слои редактора (несколько баннеров + текст) — приоритетнее одиночного баннера
        overlays = _parse_overlays(job, db)

        # 0a) Профиль уникализации, если он задан: полный конвейер одним проходом,
        # слои редактора идут внутрь того же графа.
        profile = _resolve_profile(job, account, db)
        if profile is not None:
            # Баннер задачи и слои редактора складываются, а не заменяют друг друга:
            # у частей длинного видео в overlays лежит подпись «Часть N», и при
            # выборе «или» баннер молча терялся на каждой такой задаче.
            banner_layer = _banner_layer(job, banner)
            layers = banner_layer + overlays          # баннер ниже, слои поверх него
            job.status = JobStatus.rendering
            _append_log(job, f"Уникализация по профилю «{profile.name}»…"
                             + (" Баннер вжигается в тот же проход." if banner_layer else ""))
            db.commit()
            out_name = f"job{job.id}_{int(datetime.now().timestamp())}.mp4"
            out_path = os.path.join(settings.output_dir, out_name)
            try:
                params = json.loads(profile.params) if profile.params else {}
                hook_path, overlay_png, background, bg_is_video, ad_path = _pick_assets(
                    params, db, getattr(account, "group_id", None))
                uniqueizer.render(
                    video_path=video_path,
                    output_path=out_path,
                    params=params,
                    hook_path=hook_path,
                    overlay_png=overlay_png,
                    background=background,
                    background_is_video=bg_is_video,
                    ad_path=ad_path,
                    part_start=job.part_start or 0.0,
                    part_duration=job.part_duration,
                    editor_overlays=layers or None,
                    log=_live_log_render(job, db),
                )
            except (media.MediaError, ValueError) as e:
                job.status = JobStatus.failed
                job.error = str(e)
                _append_log(job, f"Ошибка ffmpeg: {e}")
                db.commit()
                return
            job.output_filename = out_name
            source_path = out_path
            _append_log(job, "Уникализация готова.")
            db.commit()

        elif overlays:
            # Баннер задачи кладём под слои — без этого части длинного видео
            # (у них в overlays подпись «Часть N») теряли баннер и здесь тоже.
            layers = _banner_layer(job, banner) + overlays
            job.status = JobStatus.rendering
            _append_log(job, f"Накладываю слои ({len(layers)}) через ffmpeg…")
            db.commit()
            out_name = f"job{job.id}_{int(datetime.now().timestamp())}.mp4"
            out_path = os.path.join(settings.output_dir, out_name)
            try:
                media.render_with_overlays(
                    video_path=video_path,
                    overlays=layers,
                    output_path=out_path,
                    uniqueize=bool(getattr(account, "uniqueize", True)),
                )
            except media.MediaError as e:
                job.status = JobStatus.failed
                job.error = str(e)
                _append_log(job, f"Ошибка ffmpeg: {e}")
                db.commit()
                return
            job.output_filename = out_name
            source_path = out_path
            _append_log(job, "Слои наложены.")
            db.commit()

        # 1) Наложение баннера (если задан)
        elif banner is not None:
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
                    motion=getattr(banner, "motion", "none") or "none",
                    motion_speed=getattr(banner, "motion_speed", 1.0) or 1.0,
                    uniqueize=bool(getattr(account, "uniqueize", True)),
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
        elif getattr(account, "uniqueize", True):
            # Баннера нет, но включена уникализация — отдельный проход (новый хеш).
            job.status = JobStatus.rendering
            _append_log(job, "Уникализирую видео (подмена хеша)…")
            db.commit()
            out_name = f"job{job.id}_{int(datetime.now().timestamp())}.mp4"
            out_path = os.path.join(settings.output_dir, out_name)
            try:
                media.render_uniqueize(video_path=video_path, output_path=out_path)
            except media.MediaError as e:
                job.status = JobStatus.failed
                job.error = str(e)
                _append_log(job, f"Ошибка ffmpeg: {e}")
                db.commit()
                return
            job.output_filename = out_name
            source_path = out_path
            _append_log(job, "Готово (уникализировано).")
            db.commit()

        # 2) Загрузка через браузер
        job.status = JobStatus.uploading
        _append_log(job, f"Публикация в {account.platform.value}…")
        db.commit()

        proxy = parse_proxy(account.proxy_url)
        uploader = get_uploader(account.platform.value)

        def _live_log(m: str) -> None:
            """Пишем ход постинга сразу, а не пачкой в конце.

            Раньше строки копились в загрузчике и добавлялись после его выхода —
            все получали одинаковую метку времени, и по логу нельзя было понять,
            где задача простояла минуты (например, на заливке видео).
            """
            try:
                _append_log(job, m)
                db.commit()
            except Exception:  # noqa: BLE001 — лог не должен ронять постинг
                db.rollback()

        # Протухшие куки — самая частая причина провала постинга. Если у аккаунта есть
        # логин с паролем, перелогиниваемся сами и продолжаем, а не роняем задачу.
        if not _ensure_session(account, db, _live_log):
            raise UploadError(
                "Сессия аккаунта недействительна, а войти заново не удалось — "
                "проверьте логин/пароль и почту в профиле."
            )

        result = uploader(
            video_path=source_path,
            caption=job.caption or "",
            cookies_path=account.cookies_path,
            proxy=proxy,
            headless=settings.headless,
            log=_live_log,
        )
        # result.log сюда не дописываем: те же строки уже легли через _live_log

        if result.ok:
            job.status = JobStatus.done
            job.posted_url = result.url
            _append_log(job, "Задача выполнена успешно." + (f" Ссылка: {result.url}" if result.url else ""))
        else:
            job.status = JobStatus.failed
            job.error = result.error or "Неизвестная ошибка постинга"
            _append_log(job, f"Не удалось опубликовать: {job.error}")
        db.commit()

        _notify_result(db, job, account, ok=result.ok)
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
