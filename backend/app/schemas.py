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
    group_id: int | None = None
    # Данные для автоматического входа (все необязательные)
    tt_login: str | None = None
    tt_password: str | None = None
    mail_address: str | None = None
    mail_password: str | None = None
    mail_imap_host: str | None = None
    mail_imap_port: int | None = None
    auto_login: bool | None = None
    # Запустить вход сразу после создания профиля
    start_login: bool = True


class AccountUpdate(BaseModel):
    # У uniq_profile_id и group_id null — это осмысленное «снять», а не «не трогать»:
    # роутер различает их по payload.model_fields_set, а не по значению.
    name: str | None = None
    uniq_profile_id: int | None = None
    group_id: int | None = None
    proxy_url: str | None = None
    active: bool | None = None
    uniqueize: bool | None = None
    tt_login: str | None = None
    tt_password: str | None = None
    mail_address: str | None = None
    mail_password: str | None = None
    mail_imap_host: str | None = None
    mail_imap_port: int | None = None
    auto_login: bool | None = None


class AccountOut(BaseModel):
    """Наружу отдаём только признаки наличия секретов, сами пароли и токены — никогда."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    platform: Platform
    proxy_url: str | None
    proxy_ok: bool | None
    proxy_ip: str | None
    proxy_checked_at: datetime | None
    uniqueize: bool
    uniq_profile_id: int | None
    group_id: int | None
    active: bool
    has_cookies: bool
    created_at: datetime
    # Автовход
    tt_login: str | None = None
    has_tt_credentials: bool = False
    mail_address: str | None = None
    mail_kind: str | None = None
    mail_connected: bool = False
    mail_connected_at: datetime | None = None
    auto_login: bool = True
    last_login_at: datetime | None = None
    login_error: str | None = None


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


class AutoLoginStateOut(BaseModel):
    """Стадия автоматического входа — фронт опрашивает её раз в пару секунд."""

    # idle | starting | filling | waiting_code | submitting_code | done | captcha | error
    stage: str
    message: str | None = None
    screenshot: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ---------- Mail ----------
class MailMessageOut(BaseModel):
    id: str
    sender: str
    subject: str
    received_at: datetime | None = None
    preview: str = ""


class MailCodeOut(BaseModel):
    code: str | None = None
    message: str | None = None


class MailConnectOut(BaseModel):
    """Device code flow: пользователь вводит код на странице Microsoft."""

    user_code: str
    verification_uri: str
    expires_in: int


class MailConnectStateOut(BaseModel):
    # pending | done | error
    state: str
    message: str | None = None


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
    ms_client_id: str | None = None


class SettingsUpdate(BaseModel):
    tg_bot_token: str | None = None   # "" очищает
    tg_chat_id: str | None = None
    tg_login_enabled: bool | None = None
    new_password: str | None = None
    ms_client_id: str | None = None   # Azure-приложение для чтения outlook-почты


# ---------- Videos ----------
class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    filename: str
    width: int | None
    height: int | None
    duration: float | None
    folder_id: int | None = None
    created_at: datetime


# ---------- Hooks / Overlays / Uniq-профили ----------
class HookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    width: int | None
    height: int | None
    duration: float | None
    folder_id: int | None = None
    created_at: datetime


class OverlayAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    created_at: datetime


class AdClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    width: int | None
    height: int | None
    duration: float | None
    created_at: datetime


class BackgroundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    is_video: bool
    folder_id: int | None = None
    created_at: datetime


# ---------- Папки библиотек ----------
class AssetFolderCreate(BaseModel):
    kind: str                      # video | hook | background
    name: str
    group_ids: list[int] = []


class AssetFolderUpdate(BaseModel):
    name: str | None = None
    group_ids: list[int] | None = None


class AssetFolderOut(BaseModel):
    id: int
    kind: str
    name: str
    group_ids: list[int]           # пустой список = папка ничего не ограничивает
    items_count: int
    created_at: datetime


class FolderAssign(BaseModel):
    """Перенос файла в папку; null — вынуть из папки."""

    folder_id: int | None = None


# ---------- Группы аккаунтов ----------
class AccountGroupCreate(BaseModel):
    name: str
    color: str | None = None


class AccountGroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class AccountGroupOut(BaseModel):
    id: int
    name: str
    color: str | None
    accounts_count: int          # для подписи «N аккаунтов» в панели
    created_at: datetime


class UniqProfileCreate(BaseModel):
    name: str
    params: dict | None = None
    is_default: bool = False


class UniqProfileUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None
    is_default: bool | None = None


class UniqProfileOut(BaseModel):
    id: int
    name: str
    params: dict          # наружу отдаём разобранным объектом, а не строкой
    is_default: bool
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
    uniq_profile_id: int | None = None
    account_id: int
    video_id: int
    banner_id: int | None = None
    caption: str = ""
    banner_x: float | None = None
    banner_y: float | None = None
    banner_scale: float | None = None
    scheduled_at: datetime | None = None
    # Слои редактора: несколько баннеров и текстов. Если заданы — имеют приоритет
    # над одиночным banner_id (см. services/media.render_with_overlays).
    overlays: list[dict] | None = None


class JobBulkCreate(BaseModel):
    """Одно видео на несколько аккаунтов: по задаче (и своему рендеру) на каждый."""

    uniq_profile_id: int | None = None
    account_ids: list[int]
    video_id: int
    banner_id: int | None = None
    caption: str = ""
    banner_x: float | None = None
    banner_y: float | None = None
    banner_scale: float | None = None
    scheduled_at: datetime | None = None
    overlays: list[dict] | None = None
    # Случайная пауза между аккаунтами, минуты: пачка не уходит залпом.
    spread_min_minutes: int = 5
    spread_max_minutes: int = 20
    # Лёгкие вариации подписи (перестановка хештегов, эмодзи в хвосте).
    vary_caption: bool = True


class JobPartsCreate(BaseModel):
    """Длинное видео → серия частей на каждый выбранный аккаунт."""

    account_ids: list[int]
    video_id: int
    parts: int
    caption: str = ""
    caption_template: str = "Часть {n}/{total}"
    label_on: bool = True                 # рисовать подпись части поверх видео
    banner_id: int | None = None
    overlays: list[dict] | None = None
    scheduled_at: datetime | None = None
    uniq_profile_id: int | None = None
    # Пауза между частями одной серии, минуты
    part_gap_min_minutes: int = 30
    part_gap_max_minutes: int = 120
    # Дополнительный разброс между аккаунтами
    spread_min_minutes: int = 0
    spread_max_minutes: int = 0


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: str | None
    uniq_profile_id: int | None
    part_index: int | None
    part_total: int | None
    account_id: int
    video_id: int
    banner_id: int | None
    caption: str
    banner_x: float | None
    banner_y: float | None
    banner_scale: float | None
    overlays: str | None      # JSON-строка со слоями (как хранится в БД)
    status: JobStatus
    scheduled_at: datetime | None
    output_filename: str | None
    error: str | None
    log: str
    posted_url: str | None
    created_at: datetime
    updated_at: datetime


class JobBulkOut(BaseModel):
    """Результат пачки: что создано и почему часть аккаунтов пропущена."""

    jobs: list[JobOut]
    skipped: list[str]
