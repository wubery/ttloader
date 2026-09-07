"""Проверка активности: барьер «только свои», отбор пар и расписание.

Главное здесь — `video_url_allowed`. Это единственное, что стоит между ботом и
лайком случайному чужому ролику, поэтому проверяется он подробнее всего.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import activity as act

PANEL = {"mine", "second", "third"}


def acc(id, handle="mine", *, active=True, likes_on=True, cookies=True,
        activity_on=True, next_at=None):
    return SimpleNamespace(id=id, tiktok_handle=handle, active=active, likes_on=likes_on,
                           has_cookies=cookies, activity_on=activity_on,
                           next_activity_at=next_at, name=f"acc{id}")


# ----------------------------------------------------------------- барьер

@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@mine/video/7123456789",
    "https://tiktok.com/@Second/video/1",              # регистр ника не важен
    "https://m.tiktok.com/@third/video/42/",
])
def test_own_posts_allowed(url):
    assert act.video_url_allowed(url, PANEL)


@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@stranger/video/7123456789",   # чужой аккаунт
    "https://www.tiktok.com/@mine.evil.com/video/1",       # похожий ник
    "https://www.tiktok.com/@mine/",                       # профиль, а не пост
    "https://www.tiktok.com/foryou",                       # лента
    "https://www.tiktok.com/@mine/video/abc",              # не числовой id
    "https://evil.com/@mine/video/1",                      # чужой домен
    "https://www.tiktok.com.evil.ru/@mine/video/1",        # домен-подделка
    "javascript:alert(1)",
    "",
    None,
])
def test_everything_else_is_blocked(url):
    assert not act.video_url_allowed(url, PANEL)


def test_empty_whitelist_blocks_everything():
    """Пока ники не определены, лайкать нечего — панель пуста, значит запрет."""
    assert not act.video_url_allowed("https://www.tiktok.com/@mine/video/1", set())


# ----------------------------------------------------------------- ники

@pytest.mark.parametrize("raw,expected", [
    ("@Name", "name"),
    ("name", "name"),
    ("https://www.tiktok.com/@Foo", "foo"),
    ("https://www.tiktok.com/@foo/video/123", "foo"),
    ("  @user.name_1 ", "user.name_1"),
    ("", None), (None, None), ("@", None), ("ник с пробелом", None),
])
def test_parse_handle(raw, expected):
    assert act.parse_handle(raw) == expected


# ----------------------------------------------------------------- пары лайков

def test_nobody_likes_themselves():
    pool = [acc(1, "mine"), acc(2, "second")]
    for _ in range(20):
        for liker, target in act.pick_like_pairs(pool, set(), 2, random.Random()):
            assert liker.id != target.id


def test_cooldown_pair_is_skipped():
    pool = [acc(1, "mine"), acc(2, "second")]
    pairs = act.pick_like_pairs(pool, {(1, 2), (2, 1)}, 2, random.Random(1))
    assert pairs == []                      # обоих адресатов лайкали недавно


def test_accounts_without_handle_are_out():
    """Без ника аккаунт не участвует ни как автор, ни как адресат."""
    pool = [acc(1, "mine"), acc(2, None), acc(3, "")]
    assert act.pick_like_pairs(pool, set(), 3, random.Random(1)) == []


def test_disabled_and_cookieless_are_out():
    pool = [acc(1, "mine", likes_on=False), acc(2, "second", cookies=False),
            acc(3, "third", active=False)]
    assert act.pick_like_pairs(pool, set(), 3, random.Random(1)) == []


def test_one_like_per_account_per_run():
    pool = [acc(i, f"h{i}") for i in range(1, 6)]
    pairs = act.pick_like_pairs(pool, set(), 5, random.Random(7))
    likers = [p[0].id for p in pairs]
    assert len(likers) == len(set(likers))


# ----------------------------------------------------------------- расписание

def test_due_only_when_time_came():
    now = datetime(2026, 9, 7, 12, 0)
    soon = acc(1, next_at=now + timedelta(hours=2))
    ready = acc(2, next_at=now - timedelta(minutes=1))
    fresh = acc(3, next_at=None)                 # ещё ни разу не ходил
    due = {a.id for a in act.due_for_activity([soon, ready, fresh], now)}
    assert due == {2, 3}


def test_disabled_account_is_never_due():
    now = datetime(2026, 9, 7, 12, 0)
    off = acc(1, activity_on=False, next_at=now - timedelta(days=1))
    assert act.due_for_activity([off], now) == []


def test_next_time_stays_inside_hours_window():
    rnd = random.Random(3)
    now = datetime(2026, 9, 7, 22, 30)
    for _ in range(100):
        t = act.next_activity_time(now, per_day_min=1, per_day_max=3,
                                   hour_from=9, hour_to=23, rnd=rnd)
        assert 9 <= t.hour < 23, t
        assert t > now


def test_window_can_be_disabled_by_equal_bounds():
    rnd = random.Random(3)
    now = datetime(2026, 9, 7, 3, 0)
    t = act.next_activity_time(now, per_day_min=1, per_day_max=1,
                               hour_from=0, hour_to=0, rnd=rnd)
    assert t > now                                # круглосуточно — сдвигать некуда


def test_session_length_inside_range():
    rnd = random.Random(5)
    for _ in range(50):
        assert 60 <= act.session_seconds(seconds_min=60, seconds_max=180, rnd=rnd) <= 180


def test_swapped_bounds_do_not_crash():
    rnd = random.Random(5)
    assert 60 <= act.session_seconds(seconds_min=180, seconds_max=60, rnd=rnd) <= 180
    t = act.next_likes_time(datetime(2026, 9, 7, 12, 0),
                            interval_min=180, interval_max=45, rnd=rnd)
    assert t > datetime(2026, 9, 7, 12, 0)


# --- Честная версия панели ----------------------------------------------------
# Обновление нельзя принимать на веру: апдейтер пишет версию после git pull, а код
# в контейнере может остаться прежним, если пересборка не доехала.

def test_version_reports_running_commit(client, monkeypatch):
    monkeypatch.setenv("VP_COMMIT", "abc1234")
    body = client.get("/api/system/version").json()
    assert body["running"] == "abc1234"
    assert "behind" in body and "code_stale" in body


def test_version_without_build_arg_does_not_cry_wolf(client, monkeypatch):
    """Старый образ без прошитого коммита не должен показывать ложную тревогу."""
    monkeypatch.delenv("VP_COMMIT", raising=False)
    body = client.get("/api/system/version").json()
    assert body["running"] == "unknown"
    assert body["code_stale"] is False


# --- Определение своего ника ---------------------------------------------------
# Ошибиться тут опаснее, чем не найти: чужой ник попал бы в белый список лайков.

def test_handle_search_ignores_arbitrary_links():
    """В ленте ссылки /@… ведут на чужих авторов — брать их нельзя."""
    from app.services.activity import OWN_PROFILE_JS

    assert "querySelectorAll('a[href^=\"/@\"]')" not in OWN_PROFILE_JS
    assert "__UNIVERSAL_DATA_FOR_REHYDRATION__" in OWN_PROFILE_JS   # состояние страницы
    assert "nav-profile" in OWN_PROFILE_JS                          # ссылка «Профиль»


def test_ownership_is_verified_by_edit_button():
    from app.services.activity import OWN_PROFILE_CHECK_JS

    assert "edit-profile" in OWN_PROFILE_CHECK_JS
    assert "редактировать профиль" in OWN_PROFILE_CHECK_JS.lower()


def test_studio_is_tried_before_feed():
    """В студии профиль всегда свой, поэтому она первый источник."""
    import inspect

    from app.services import activity as act

    src = inspect.getsource(act.discover_handle)
    assert src.index("STUDIO_URL") < src.index("FEED_URL")
