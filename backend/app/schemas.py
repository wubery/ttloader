from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import BannerType, JobStatus, Platform


# ---------- Accounts ----------
class AccountCreate(BaseModel):
    name: str
    platform: Platform
    proxy_url: str | None = None
    uniqueize: bool | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    proxy_url: str | None = None
    active: bool | None = None
    uniqueize: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    platform: Platform
    proxy_url: str | None
    proxy_ok: bool | None
    proxy_ip: str | None
    proxy_checked_at: datetime | None
    uniqueize: bool
    active: bool
    has_cookies: bool
    created_at: datetime


class ProxyCheckOut(BaseModel):
    ok: bool
    ip: str | None = None
    error: str | None = None


class LoginCredentialsIn(BaseModel):
    username: str
    password: str


class LoginCodeIn(BaseModel):
    code: str


class LoginStageOut(BaseModel):
    # done | email_code | captcha | unknown
    stage: str
    screenshot: str | None = None  # data:image/png;base64,... для стадии captcha
    message: str | None = None


class LoginStatusOut(BaseModel):
    active: bool
    account_id: int | None = None
    account_name: str | None = None


# ---------- Auth / Settings ----------
class LoginIn(BaseModel):
    username: str
    password: str


class TelegramCodeIn(BaseModel):
    code: str


class AuthMeOut(BaseModel):
    authenticated: bool
    username: str | None = None
    tg_login: bool = False


class SettingsOut(BaseModel):
    admin_user: str
    tg_bot_configured: bool
    tg_chat_id: str | None
    tg_login_enabled: bool


class SettingsUpdate(BaseModel):
    tg_bot_token: str | None = None   # "" очищает
    tg_chat_id: str | None = None
    tg_login_enabled: bool | None = None
    new_password: str | None = None


# ---------- Videos ----------
class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    filename: str
    width: int | None
    height: int | None
    duration: float | None
    created_at: datetime


# ---------- Banners ----------
class BannerUpdate(BaseModel):
    name: str | None = None
    x: float | None = None
    y: float | None = None
    scale: float | None = None
    opacity: float | None = None
    motion: str | None = None
    motion_speed: float | None = None


class BannerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: BannerType
    filename: str
    x: float
    y: float
    scale: float
    opacity: float
    motion: str
    motion_speed: float
    created_at: datetime


# ---------- Jobs ----------
class JobCreate(BaseModel):
    account_id: int
    video_id: int
    banner_id: int | None = None
    caption: str = ""
    banner_x: float | None = None
    banner_y: float | None = None
    banner_scale: float | None = None
    scheduled_at: datetime | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    video_id: int
    banner_id: int | None
    caption: str
    banner_x: float | None
    banner_y: float | None
    banner_scale: float | None
    status: JobStatus
    scheduled_at: datetime | None
    output_filename: str | None
    error: str | None
    log: str
    posted_url: str | None
    created_at: datetime
    updated_at: datetime
