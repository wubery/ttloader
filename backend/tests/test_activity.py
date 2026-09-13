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


def test_version_flags_dead_updater(client):
    """«Запрошено обновление…» не должно висеть молча: панель обязана сказать,
    что хостовый апдейтер не отвечает."""
    body = client.get("/api/system/version").json()
    assert "updater_alive" in body and "updater_seen" in body
    # в тестах апдейтера нет вовсе — значит и признаков жизни быть не должно
    assert body["updater_alive"] is False
    assert body["updater_seen"] is None


# --- Разгон нового аккаунта ----------------------------------------------------
# Смысл разгона в том, что свежий аккаунт работает не в полную силу. Проверяем
# края шкалы: в первый день — заданная доля, к последнему — полная нагрузка.

def test_warmup_starts_low_and_reaches_full():
    start = datetime(2026, 9, 1, 10, 0)
    first = act.warmup_factor(start, start, days=14, start_percent=25)
    last = act.warmup_factor(start, start + timedelta(days=13), days=14, start_percent=25)
    assert first == pytest.approx(0.25)
    assert last == pytest.approx(1.0)


def test_warmup_is_monotonic():
    start = datetime(2026, 9, 1)
    seen = [act.warmup_factor(start, start + timedelta(days=d), days=14, start_percent=25)
            for d in range(20)]
    assert seen == sorted(seen)
    assert seen[-1] == 1.0


def test_warmup_after_period_is_full():
    start = datetime(2026, 9, 1)
    assert act.warmup_factor(start, start + timedelta(days=99), days=14,
                             start_percent=25) == 1.0


def test_warmup_can_be_switched_off():
    start = datetime(2026, 9, 1)
    assert act.warmup_factor(start, start, days=14, start_percent=25, enabled=False) == 1.0


def test_warmup_without_start_date_counts_first_day():
    assert act.warmup_day(None, datetime(2026, 9, 10)) == 1


def test_scaled_range_never_collapses_to_zero():
    """Даже при сильном сжатии сессия остаётся осмысленной, а не нулевой."""
    lo, hi = act.scale_range(180, 600, 0.05, floor=20)
    assert lo >= 20 and hi >= lo


def test_scaled_range_keeps_bounds_ordered():
    assert act.scale_range(600, 180, 0.5) == act.scale_range(180, 600, 0.5)


def test_likes_wait_for_the_account_to_settle():
    start = datetime(2026, 9, 1, 12, 0)
    assert not act.likes_allowed(start, start, after_day=4)
    assert not act.likes_allowed(start, start + timedelta(days=2), after_day=4)
    assert act.likes_allowed(start, start + timedelta(days=3), after_day=4)


def test_likes_unrestricted_when_warmup_is_off():
    start = datetime(2026, 9, 1)
    assert act.likes_allowed(start, start, after_day=4, enabled=False)


# --- Досмотр -------------------------------------------------------------------
# Прежняя версия держала каждый ролик одинаковые 2–8 секунд и не досматривала
# ничего. Проверяем, что теперь время считается от длины ролика.

def test_watch_plan_scales_with_duration():
    """Диапазоны пересекаются (короткий ролик можно пересмотреть), важна средняя."""
    rnd = random.Random(0)
    short = [act.watch_plan(5.0, rnd)[0] for _ in range(400)]
    long = [act.watch_plan(60.0, rnd)[0] for _ in range(400)]
    assert sum(long) / len(long) > 5 * sum(short) / len(short)


def test_watch_plan_sometimes_finishes_the_video():
    rnd = random.Random(1)
    kinds = [act.watch_plan(20.0, rnd)[1] for _ in range(300)]
    assert "досмотрел" in kinds
    assert "пересмотрел" in kinds
    assert "бросил" in kinds


def test_watch_plan_survives_unknown_duration():
    """Пока длительность не подгрузилась, всё равно нужна разумная пауза."""
    rnd = random.Random(2)
    for _ in range(50):
        seconds, kind = act.watch_plan(0.0, rnd)
        assert 3.0 <= seconds <= 13.0
        assert kind == "без длительности"


def test_browse_uses_the_plan_not_a_fixed_pause():
    import inspect

    src = inspect.getsource(act.browse_feed)
    assert "watch_plan" in src
    assert "ACTIVE_VIDEO_JS" in src


# --- Расписание и лайки --------------------------------------------------------

def test_sessions_spread_over_the_whole_window():
    """Раньше всё, что не попало в окно, сваливалось в его первый час."""
    rnd = random.Random(11)
    now = datetime(2026, 9, 7, 23, 30)
    hours = {act.next_activity_time(now, per_day_min=1, per_day_max=1,
                                    hour_from=9, hour_to=23, rnd=rnd).hour
             for _ in range(200)}
    assert min(hours) >= 9 and max(hours) < 23
    assert max(hours) >= 20          # добирается до конца окна
    assert len(hours) >= 8           # а не толпится в одном часу


def test_no_mutual_likes_within_one_run():
    pool = [acc(1, "mine"), acc(2, "second")]
    for seed in range(50):
        pairs = act.pick_like_pairs(pool, set(), 2, random.Random(seed))
        ids = {(liker.id, target.id) for liker, target in pairs}
        assert not ({(1, 2), (2, 1)} <= ids), "аккаунты лайкнули друг друга в один прогон"


def test_reciprocation_is_allowed_on_another_run():
    """Ответный лайк через сутки — обычное поведение, запрещать его незачем."""
    pool = [acc(1, "mine"), acc(2, "second")]
    pairs = act.pick_like_pairs(pool, {(1, 2)}, 1, random.Random(3))
    assert [(p[0].id, p[1].id) for p in pairs] == [(2, 1)]


# --- Разгон через API ----------------------------------------------------------
# Проверяем сквозь настоящую схему: колонки добавляются автомиграцией, и без неё
# вкладка «Активность» упала бы на первом же запросе.

def test_warmup_settings_round_trip(client):
    saved = client.post("/api/activity/settings", json={
        "warmup_enabled": True, "warmup_days": 10,
        "warmup_start_percent": 30, "warmup_likes_after_day": 3,
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["warmup_days"] == 10 and body["warmup_start_percent"] == 30
    assert client.get("/api/activity/settings").json()["warmup_likes_after_day"] == 3


def test_warmup_settings_reject_nonsense(client):
    assert client.post("/api/activity/settings",
                       json={"warmup_start_percent": 0}).status_code == 400
    assert client.post("/api/activity/settings",
                       json={"warmup_days": 999}).status_code == 400


def test_warmup_endpoint_reports_every_active_account(client):
    created = client.post("/api/accounts", json={"name": "разгон", "platform": "tiktok"})
    assert created.status_code in (200, 201), created.text
    acc_id = created.json()["id"]

    client.post("/api/activity/settings", json={
        "warmup_enabled": True, "warmup_days": 14, "warmup_start_percent": 25,
        "warmup_likes_after_day": 4})
    rows = client.get("/api/activity/warmup").json()
    mine = [r for r in rows if r["account_id"] == acc_id]
    assert len(mine) == 1
    row = mine[0]
    assert row["day"] == 1 and row["days_total"] == 14
    assert row["percent"] == 25          # первый день — стартовая доля
    assert row["likes_allowed"] is False  # лайки только с четвёртого дня


def test_warmup_can_be_restarted(client):
    acc_id = client.post("/api/accounts",
                         json={"name": "заново", "platform": "tiktok"}).json()["id"]
    r = client.post(f"/api/activity/warmup/{acc_id}/restart")
    assert r.status_code == 200, r.text
    rows = {x["account_id"]: x for x in client.get("/api/activity/warmup").json()}
    assert rows[acc_id]["started_at"] is not None
    assert rows[acc_id]["day"] == 1
