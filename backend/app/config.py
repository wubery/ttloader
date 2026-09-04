from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень бэкенда (…/backend)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./video_poster.db"
    frontend_url: str = "http://localhost:5173"
    timezone: str = "Europe/Moscow"

    # Каталоги хранения (создаются автоматически при старте).
    # Все считаются ОТ data_dir: иначе достаточно поменять DATA_DIR — и часть файлов
    # уедет в новое место, а часть останется в старом. Так уже терялись хуки и фоны
    # (уходили в /app/data мимо тома и пропадали при пересборке образа). Явные
    # VIDEOS_DIR/HOOKS_DIR и т.п. по-прежнему главнее вычисленного значения.
    data_dir: str = str(BASE_DIR / "data")
    videos_dir: str | None = None
    banners_dir: str | None = None
    output_dir: str | None = None
    cookies_dir: str | None = None
    hooks_dir: str | None = None
    overlays_dir: str | None = None
    backgrounds_dir: str | None = None
    ads_dir: str | None = None

    @model_validator(mode="after")
    def _derive_dirs(self) -> "Settings":
        base = Path(self.data_dir)
        for name, folder in (("videos_dir", "videos"), ("banners_dir", "banners"),
                             ("output_dir", "output"), ("cookies_dir", "cookies"),
                             ("hooks_dir", "hooks"), ("overlays_dir", "overlays"),
                             ("backgrounds_dir", "backgrounds"), ("ads_dir", "ads")):
            if not getattr(self, name):
                object.__setattr__(self, name, str(base / folder))
        return self

    # Внешние бинарники
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # Playwright: показывать окно браузера при постинге (удобно для отладки)
    headless: bool = True

    # Максимум одновременных задач постинга
    max_concurrent_jobs: int = 2

    # Период автопроверки прокси аккаунтов (минуты). 0 — выключить.
    proxy_check_minutes: int = 30

    # Период проверки живости кук и автоперелогина (часы). 0 — выключить.
    # Часы, а не минуты: каждый вход — запуск браузера и лишний повод для подозрений.
    session_check_hours: int = 6

    # Сколько дней держать в output_dir скриншоты, превью и осиротевшие рендеры
    output_keep_days: int = 14

    # --- Качество кодирования -------------------------------------------------
    # CRF берётся случайным из диапазона: это ещё и часть уникализации (другой
    # битрейт → другой хеш). Чем меньше число, тем лучше картинка и больше файл.
    # 18–20 — визуально «без потерь» для соцсетей; было 19–23, и на 23 картинка
    # заметно сыпалась. preset влияет на скорость: veryfast ≈ втрое быстрее medium.
    video_crf_min: int = 18
    video_crf_max: int = 20
    video_preset: str = "veryfast"
    audio_bitrate: str = "192k"

    # Принудительный шум в старом пути уникализации (без профиля). Выключен:
    # шум сильнее всего портил картинку, а хеш и так меняют микрокроп, eq и
    # случайные метаданные. В профилях шум остаётся отдельной настройкой.
    uniq_force_noise: bool = False

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.banners_dir, self.output_dir,
                  self.cookies_dir, self.hooks_dir, self.overlays_dir,
                  self.backgrounds_dir, self.ads_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
