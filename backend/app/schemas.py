from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .models import BannerType, JobStatus, Platform


# ---------- Accounts ----------
class AccountCreate(BaseModel):
    name: str
    platform: Platform
    proxy_url: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    proxy_url: str | None = None
    active: bool | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    platform: Platform
    proxy_url: str | None
    active: bool
    has_cookies: bool
    created_at: datetime


class ProxyCheckOut(BaseModel):
    ok: bool
    ip: str | None = None
    error: str | None = None


class LoginStartOut(BaseModel):
    account_id: int
    novnc_url: str


class LoginStatusOut(BaseModel):
    active: bool
    account_id: int | None = None
    account_name: str | None = None


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
