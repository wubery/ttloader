from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import SessionLocal, init_db
from .routers import (account_groups, accounts, activity, ads, asset_folders, auth,
                      backgrounds, banners, hooks, jobs, overlays,
                      settings as settings_router, stats, system, uniq_profiles, videos)
from .scheduler import shutdown_scheduler, start_scheduler
from .services import telegram
from .services.appsettings import bootstrap_settings, get_settings_row
from .services.security import verify_session

# Пути, доступные без авторизации
_OPEN_PREFIXES = ("/api/auth/", "/api/health")


def _repair_tiktok_links() -> None:
    """Дописывает ник в старые ссылки на ролики TikTok (jobs.posted_url).

    До появления ника в ссылке сохранялась форма /video/<id>, которую TikTok
    отдаёт как 404. Разовая починка при старте: где ник аккаунта известен —
    ссылка становится рабочей, где нет — остаётся как была.
    """
    from .services.tiktok_links import repair_job_urls

    db = SessionLocal()
    try:
        fixed = repair_job_urls(db)
        if fixed:
            print(f"[links] Исправлено ссылок на ролики TikTok: {fixed}", flush=True)
    except Exception as e:  # noqa: BLE001 — панель должна подняться в любом случае
        db.rollback()
        print(f"[links] Не удалось починить ссылки: {e}", flush=True)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_settings()
    _repair_tiktok_links()
    start_scheduler()
    telegram.start_bot()
    yield
    telegram.stop_bot()
    shutdown_scheduler()


app = FastAPI(title="Video Poster", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """Требует валидную сессию для /api/* (кроме /api/auth/* и /api/health)."""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(_OPEN_PREFIXES):
        db = SessionLocal()
        try:
            row = get_settings_row(db)
            user = verify_session(request.cookies.get("vp_session"), row.session_secret or "")
        finally:
            db.close()
        if user is None:
            return JSONResponse({"detail": "Требуется вход в панель"}, status_code=401)
    return await call_next(request)


app.include_router(auth.router)
app.include_router(settings_router.router)
app.include_router(system.router)
app.include_router(accounts.router)
app.include_router(account_groups.router)
app.include_router(activity.router)
app.include_router(asset_folders.router)
app.include_router(videos.router)
app.include_router(banners.router)
app.include_router(hooks.router)
app.include_router(backgrounds.router)
app.include_router(ads.router)
app.include_router(overlays.router)
app.include_router(uniq_profiles.router)
app.include_router(jobs.router)
app.include_router(stats.router)


@app.get("/api/health")
def health():
    from .services import media

    ffmpeg_ok = True
    ffmpeg_err = None
    try:
        media._run([settings.ffmpeg_bin, "-version"])
    except media.MediaError as e:
        ffmpeg_ok = False
        ffmpeg_err = str(e)

    playwright_ok = True
    try:
        import playwright  # noqa: F401
    except ImportError:
        playwright_ok = False

    # Свободное место — частая причина «загрузка оборвалась»: диск кончается молча,
    # и наружу это выглядит сетевой ошибкой браузера.
    disk_free = disk_total = None
    try:
        from .services.storage import free_space

        settings.ensure_dirs()
        disk_free, disk_total = free_space(settings.data_dir)
    except OSError:
        pass

    return {
        "status": "ok",
        "ffmpeg": ffmpeg_ok,
        "ffmpeg_error": ffmpeg_err,
        "playwright": playwright_ok,
        "disk_free": disk_free,
        "disk_total": disk_total,
    }
