from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень бэкенда (…/backend)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./video_poster.db"
    frontend_url: str = "http://localhost:5173"
    timezone: str = "Europe/Moscow"

    # Каталоги хранения (создаются автоматически при старте)
    data_dir: str = str(BASE_DIR / "data")
    videos_dir: str = str(BASE_DIR / "data" / "videos")
    banners_dir: str = str(BASE_DIR / "data" / "banners")
    output_dir: str = str(BASE_DIR / "data" / "output")
    cookies_dir: str = str(BASE_DIR / "data" / "cookies")

    # Внешние бинарники
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # Playwright: показывать окно браузера при постинге (удобно для отладки)
    headless: bool = True

    # Максимум одновременных задач постинга
    max_concurrent_jobs: int = 2

    # Период автопроверки прокси аккаунтов (минуты). 0 — выключить.
    proxy_check_minutes: int = 30

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.banners_dir, self.output_dir, self.cookies_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
