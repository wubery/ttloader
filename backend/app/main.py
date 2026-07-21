from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routers import accounts, banners, jobs, videos
from .scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Video Poster", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
