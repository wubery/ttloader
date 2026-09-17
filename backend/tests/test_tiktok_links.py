"""Ссылка на опубликованный ролик обязана содержать ник автора.

TikTok отдаёт https://www.tiktok.com/video/<id> как 404 (редирект на
/404?fromUrl=…), работает только https://www.tiktok.com/@<ник>/video/<id>.
Раньше загрузчик сохранял первую форму — все ссылки в панели вели в никуда.

Проверяем и разбор ссылок, и починку уже сохранённых записей: старые задачи
не должны ломаться, а с известным ником — должны становиться рабочими.
"""
from __future__ import annotations

import pytest

from app.services.tiktok_links import parse_video_link, repair_job_urls, video_url, with_handle

BARE = "https://www.tiktok.com/video/7683929703043829014"
GOOD = "https://www.tiktok.com/@user914224979847/video/7683929703043829014"


def test_video_url_builds_working_form():
    assert video_url("user914224979847", "7683929703043829014") == GOOD


@pytest.mark.parametrize("handle", ["@user914224979847", "User914224979847",
                                    "https://www.tiktok.com/@user914224979847"])
def test_handle_is_normalised(handle):
    assert video_url(handle, "7683929703043829014") == GOOD


@pytest.mark.parametrize("handle, video_id", [
    (None, "7683929703043829014"),   # без ника ссылка была бы 404 — лучше никакой
    ("", "7683929703043829014"),
    ("ник с пробелом", "7683929703043829014"),
    ("user914224979847", None),
    ("user914224979847", "не число"),
])
def test_no_url_without_both_parts(handle, video_id):
    assert video_url(handle, video_id) is None


def test_parse_bare_and_full_links():
    assert parse_video_link(BARE) == (None, "7683929703043829014")
    assert parse_video_link(GOOD) == ("user914224979847", "7683929703043829014")
    assert parse_video_link("https://www.tiktok.com/@user914224979847") is None
    assert parse_video_link(None) is None


def test_with_handle_fixes_bare_link():
    assert with_handle(BARE, "user914224979847") == GOOD


def test_with_handle_keeps_everything_else():
    # ник уже в ссылке — тот, что напечатал сам TikTok, надёжнее нашего
    assert with_handle(GOOD, "someone_else") == GOOD
    # ника нет — ссылку не портим, пусть остаётся как была
    assert with_handle(BARE, None) == BARE
    assert with_handle(BARE, "ник с пробелом") == BARE
    # не ссылка на ролик — не наше дело
    assert with_handle("https://youtu.be/abc", "user914224979847") == "https://youtu.be/abc"
    assert with_handle(None, "user914224979847") is None


def test_repair_job_urls(client):
    """Починка сохранённых ссылок: с ником — исправляются, без ника — целы."""
    from app.db import SessionLocal
    from app.models import Account, Job, JobStatus, Platform

    db = SessionLocal()
    try:
        with_nick = Account(name="acc-with-handle", platform=Platform.tiktok,
                            tiktok_handle="user914224979847")
        without = Account(name="acc-no-handle", platform=Platform.tiktok)
        db.add_all([with_nick, without])
        db.commit()

        fixable = Job(account_id=with_nick.id, video_id=1, caption="",
                      status=JobStatus.done, posted_url=BARE)
        already_ok = Job(account_id=with_nick.id, video_id=1, caption="",
                         status=JobStatus.done, posted_url=GOOD)
        unknown = Job(account_id=without.id, video_id=1, caption="",
                      status=JobStatus.done, posted_url=BARE)
        empty = Job(account_id=with_nick.id, video_id=1, caption="",
                    status=JobStatus.done, posted_url=None)
        db.add_all([fixable, already_ok, unknown, empty])
        db.commit()

        assert repair_job_urls(db) == 1
        db.refresh(fixable), db.refresh(already_ok), db.refresh(unknown), db.refresh(empty)
        assert fixable.posted_url == GOOD
        assert already_ok.posted_url == GOOD          # не переписали
        assert unknown.posted_url == BARE             # ник неизвестен — не тронули
        assert empty.posted_url is None
        assert repair_job_urls(db) == 0               # повторный прогон ничего не меняет
    finally:
        db.close()
