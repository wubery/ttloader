"""Ссылки на опубликованные ролики TikTok: канонический вид и починка старых.

TikTok отдаёт 404 на https://www.tiktok.com/video/<id> — рабочая форма
обязательно содержит ник автора: https://www.tiktok.com/@<ник>/video/<id>.
Загрузчик берёт id из ответа API публикации, а ника в этом ответе нет, поэтому
раньше в jobs.posted_url складывалась именно нерабочая «голая» форма.

Здесь только чистая работа со строками плюс дозаполнение уже сохранённых
ссылок: id в них есть, не хватает лишь ника, который известен из аккаунта.
"""
from __future__ import annotations

import re

from .activity import parse_handle

VIDEO_URL_TMPL = "https://www.tiktok.com/@{handle}/video/{video_id}"

# Обе формы: правильная /@ник/video/<id> и «голая» /video/<id>
_LINK_RE = re.compile(
    r"tiktok\.com/(?:@([A-Za-z0-9._]{1,64})/)?video/(\d{6,})",
    re.IGNORECASE,
)


def video_url(handle: str | None, video_id: str | None) -> str | None:
    """Рабочая ссылка на ролик. Без ника или без id — None: 404 лучше не сохранять."""
    h = parse_handle(handle)
    vid = (video_id or "").strip()
    if not h or not vid.isdigit():
        return None
    return VIDEO_URL_TMPL.format(handle=h, video_id=vid)


def parse_video_link(url: str | None) -> tuple[str | None, str] | None:
    """«…/@ник/video/123» → («ник», «123»); «…/video/123» → (None, «123»)."""
    if not url:
        return None
    m = _LINK_RE.search(url)
    if not m:
        return None
    return parse_handle(m.group(1)), m.group(2)


def with_handle(url: str | None, handle: str | None) -> str | None:
    """Дописывает ник в ссылку без него. Всё остальное возвращает как есть.

    Ссылку с уже указанным ником не трогаем: там ник самого TikTok, и он
    надёжнее того, что записан в панели.
    """
    if not url:
        return url
    parsed = parse_video_link(url)
    if parsed is None:
        return url
    existing, video_id = parsed
    if existing:
        return url
    return video_url(handle, video_id) or url


def repair_job_urls(db, account_id: int | None = None) -> int:
    """Дописывает ник в старые jobs.posted_url. Возвращает число исправленных.

    Записи аккаунтов с неизвестным ником не меняются — они остаются в прежнем
    виде и ничего не ломают, а починятся сами, как только ник станет известен
    (при публикации или через «Определить ник» в аккаунте).
    """
    from ..models import Job

    q = db.query(Job).filter(
        Job.posted_url.is_not(None),
        Job.posted_url.like("%tiktok.com/video/%"),
    )
    if account_id is not None:
        q = q.filter(Job.account_id == account_id)

    fixed = 0
    for job in q.all():
        account = job.account
        new_url = with_handle(job.posted_url, getattr(account, "tiktok_handle", None))
        if new_url and new_url != job.posted_url:
            job.posted_url = new_url
            fixed += 1
    if fixed:
        db.commit()
    return fixed
