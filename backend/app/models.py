from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class AppSettings(Base):
    """Единственная строка настроек панели (id=1): вход и Telegram."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    admin_user: Mapped[str] = mapped_column(String(120), default="admin")
    admin_pass_hash: Mapped[str | None] = mapped_column(String(255), default=None)
    session_secret: Mapped[str | None] = mapped_column(String(128), default=None)
    # Telegram
    tg_bot_token: Mapped[str | None] = mapped_column(String(120), default=None)
    tg_chat_id: Mapped[str | None] = mapped_column(String(64), default=None)
    tg_login_enabled: Mapped[bool] = mapped_column(default=False)


class Platform(str, enum.Enum):
    tiktok = "tiktok"
    youtube = "youtube"


class JobStatus(str, enum.Enum):
    pending = "pending"        # ждёт своего времени / в очереди
    rendering = "rendering"    # накладывается баннер (ffmpeg)
    uploading = "uploading"    # идёт постинг через браузер
    done = "done"
    failed = "failed"


class BannerType(str, enum.Enum):
    image = "image"   # статичная картинка (PNG/JPG)
    video = "video"   # зацикленное видео (mp4/webm/mov)


class Account(Base):
    """Аккаунт соцсети. Авторизация — через сохранённые куки (storage_state Playwright).
    К аккаунту привязывается личный прокси, чтобы IP всегда был одинаковым."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    # Путь к файлу storage_state (куки + localStorage), внутри cookies_dir
    cookies_path: Mapped[str | None] = mapped_column(String(500), default=None)
    # Прокси в формате http://user:pass@host:port или socks5://host:port
    proxy_url: Mapped[str | None] = mapped_column(String(300), default=None)
    # Результат последней проверки прокси (обновляет планировщик и кнопка «Проверить IP»)
    proxy_ok: Mapped[bool | None] = mapped_column(default=None)
    proxy_ip: Mapped[str | None] = mapped_column(String(64), default=None)
    proxy_checked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # Уникализация видео (подмена хеша/фингерпринта) перед постингом
    uniqueize: Mapped[bool] = mapped_column(default=True, server_default="1")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    jobs: Mapped[list[Job]] = relationship(back_populates="account", cascade="all, delete-orphan")

    @property
    def has_cookies(self) -> bool:
        import os

        return bool(self.cookies_path and os.path.exists(self.cookies_path))


class Video(Base):
    """Исходное видео, загруженное через панель."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(500))  # относительно videos_dir
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    duration: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    jobs: Mapped[list[Job]] = relationship(back_populates="video")


class Banner(Base):
    """Баннер (водяной знак). Картинка или зацикленное видео.
    Позиция/масштаб задаются в панели как доля от размера кадра (0..1),
    чтобы корректно ложиться на видео любого разрешения."""

    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[BannerType] = mapped_column(Enum(BannerType))
    filename: Mapped[str] = mapped_column(String(500))  # относительно banners_dir
    # Позиция и размер как доля от кадра (0..1). x/y — левый верхний угол.
    x: Mapped[float] = mapped_column(Float, default=0.05)
    y: Mapped[float] = mapped_column(Float, default=0.05)
    scale: Mapped[float] = mapped_column(Float, default=0.25)  # ширина баннера / ширина кадра
    opacity: Mapped[float] = mapped_column(Float, default=1.0)
    # Движение баннера по кадру: none | drift | bounce | slide; motion_speed — множитель.
    motion: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    motion_speed: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    jobs: Mapped[list[Job]] = relationship(back_populates="banner")


class Job(Base):
    """Задача на постинг: видео + (опц.) баннер → аккаунт, в назначенное время."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"))
    banner_id: Mapped[int | None] = mapped_column(ForeignKey("banners.id"), default=None)

    caption: Mapped[str] = mapped_column(Text, default="")
    # Переопределение позиции баннера для конкретной задачи (иначе берётся из Banner)
    banner_x: Mapped[float | None] = mapped_column(Float, default=None)
    banner_y: Mapped[float | None] = mapped_column(Float, default=None)
    banner_scale: Mapped[float | None] = mapped_column(Float, default=None)

    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.pending)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    output_filename: Mapped[str | None] = mapped_column(String(500), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    log: Mapped[str] = mapped_column(Text, default="")
    posted_url: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    account: Mapped[Account] = relationship(back_populates="jobs")
    video: Mapped[Video] = relationship(back_populates="jobs")
    banner: Mapped[Banner | None] = relationship(back_populates="jobs")
