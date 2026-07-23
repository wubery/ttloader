from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import SessionLocal, init_db
from .routers import accounts, auth, banners, jobs, settings as settings_router, system, videos
from .scheduler import shutdown_scheduler, start_scheduler
from .services import telegram
from .services.appsettings import bootstrap_settings, get_settings_row
from .services.security import verify_session

# Пути, доступные без авторизации
_OPEN_PREFIXES = ("/api/auth/", "/api/health")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bootstrap_settings()
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
app.include_router(videos.router)
app.include_router(banners.router)
app.include_router(jobs.router)


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

    return {
        "status": "ok",
        "ffmpeg": ffmpeg_ok,
        "ffmpeg_error": ffmpeg_err,
        "playwright": playwright_ok,
    }
