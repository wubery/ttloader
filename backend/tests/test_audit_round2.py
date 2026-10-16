"""Аудит, второй круг: коды входа, единые часы, описание, вход без сессии,
автомиграция, занятый аккаунт, мелочи."""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import clock
from app.config import settings
from app.db import SessionLocal
from app.models import Account, Job, JobStat, JobStatus, Platform, Video


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


def _account(db, **kw) -> Account:
    acc = Account(name=f"r2_{uuid.uuid4().hex[:6]}", platform=Platform.tiktok, **kw)
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _video(db) -> Video:
    v = Video(title="r2", filename=f"r2_{uuid.uuid4().hex[:6]}.mp4")
    db.add(v); db.commit(); db.refresh(v)
    return v


# ------------------------------------------------------------- 1. Коды входа

@pytest.fixture
def tg(monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(telegram, "_settings", lambda: ("TOKEN", ["1"], True))
    sent: list[str] = []
    monkeypatch.setattr(telegram, "send_message_detail",
                        lambda tok, cid, text_: (sent.append(text_), (True, None))[1])
    telegram.reset_login_codes()
    yield telegram, sent
    telegram.reset_login_codes()


def _code(msg: str) -> str:
    import re
    return re.search(r"\d{6}", msg).group(0)


def test_only_one_code_and_requests_are_throttled(client, tg):
    telegram, sent = tg
    assert client.post("/api/auth/telegram/request").status_code == 200
    r = client.post("/api/auth/telegram/request")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert len(sent) == 1                                # чат не заваливается


def test_new_code_replaces_old(client, tg, monkeypatch):
    telegram, sent = tg
    t = [1_000_000.0]
    monkeypatch.setattr(telegram.time, "time", lambda: t[0])
    assert telegram.issue_login_code() == "ok"
    first = _code(sent[-1])
    t[0] += telegram.CODE_REQUEST_INTERVAL + 1
    assert telegram.issue_login_code() == "ok"
    second = _code(sent[-1])
    if first != second:
        assert not telegram.check_login_code(first)       # прежний больше не действует
    assert telegram.check_login_code(second)
    assert not telegram.check_login_code(second)          # одноразовый


def test_code_requests_capped_per_window(tg, monkeypatch):
    telegram, _ = tg
    t = [2_000_000.0]
    monkeypatch.setattr(telegram.time, "time", lambda: t[0])
    for _ in range(telegram.CODE_REQUESTS_PER_WINDOW):
        assert telegram.issue_login_code() == "ok"
        t[0] += telegram.CODE_REQUEST_INTERVAL + 1
    assert telegram.issue_login_code().startswith("rate_limited:")


def test_code_expires(tg, monkeypatch):
    telegram, sent = tg
    t = [3_000_000.0]
    monkeypatch.setattr(telegram.time, "time", lambda: t[0])
    telegram.issue_login_code()
    t[0] += telegram.CODE_TTL + 1
    assert not telegram.check_login_code(_code(sent[-1]))


# ------------------------------------------------------------- 2. Единые часы

def test_clock_is_in_panel_zone():
    from zoneinfo import ZoneInfo

    expected = datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    assert abs((clock.now() - expected).total_seconds()) < 5


def test_scheduled_post_keeps_its_instant(client, db, monkeypatch):
    """Пост через 30 минут не уходит сразу и отдаётся наружу с поясом."""
    import app.scheduler as sch
    from app.services import posting

    submitted: list[int] = []
    monkeypatch.setattr(sch, "submit_job", submitted.append)
    monkeypatch.setattr(posting, "_skip_reason", lambda _db, _id: None)
    acc, vid = _account(db), _video(db)
    when = datetime.now(timezone.utc) + timedelta(minutes=30)
    r = client.post("/api/jobs/bulk", json={"account_ids": [acc.id], "video_id": vid.id,
                                            "scheduled_at": when.strftime("%Y-%m-%dT%H:%M:%S.000Z")})
    job = r.json()["jobs"][0]
    assert job["id"] not in submitted
    back = datetime.fromisoformat(job["scheduled_at"])
    assert back.tzinfo is not None and abs((back - when).total_seconds()) < 1
    stored = db.get(Job, job["id"]).scheduled_at
    assert abs((stored - clock.to_local(when)).total_seconds()) < 1


def test_api_dates_carry_zone(client, db):
    acc = _account(db)
    body = next(a for a in client.get("/api/accounts").json() if a["id"] == acc.id)
    created = datetime.fromisoformat(body["created_at"])
    assert created.tzinfo is not None
    assert abs((created - datetime.now(timezone.utc)).total_seconds()) < 120


def test_mail_code_search_uses_panel_time(monkeypatch):
    from types import SimpleNamespace

    from app.services import mail

    msg = mail.MailMessage(id="1", sender="TikTok <noreply@account.tiktok.com>",
                           subject="Your verification code is 123456",
                           received_at=datetime.now(timezone.utc))
    monkeypatch.setattr(mail, "list_messages", lambda *a, **k: [msg])
    since = clock.now() - timedelta(seconds=30)            # вход начался только что
    assert mail.find_login_code(SimpleNamespace(id=1), None, since=since) == "123456"


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Отдельная база: перевод дат трогает все таблицы, общую тестовую не портим."""
    import app.db as dbmod

    from app.db import Base

    eng = create_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(dbmod, "engine", eng)
    monkeypatch.setattr(dbmod, "SessionLocal", sessionmaker(bind=eng, future=True))
    return eng


def test_legacy_times_are_moved_into_panel_zone(temp_db, monkeypatch):
    from app.models import AppSettings

    monkeypatch.setattr(clock, "_system_zone", lambda: timezone.utc)
    S = sessionmaker(bind=temp_db)
    with S() as s:
        s.add(AppSettings(id=1))
        acc = Account(name="legacy", platform=Platform.tiktok)
        vid = Video(title="v", filename="v.mp4")
        s.add_all([acc, vid]); s.commit()
        utc_wall = datetime(2026, 10, 1, 12, 0)
        s.add(Job(account_id=acc.id, video_id=vid.id, scheduled_at=utc_wall, retry_at=utc_wall,
                  created_at=utc_wall, updated_at=utc_wall))
        s.commit()
    assert clock.migrate_stored_times() > 0
    with S() as s:
        j = s.query(Job).one()
        expect = clock.convert(datetime(2026, 10, 1, 12, 0), timezone.utc, clock.TZ)
        assert j.scheduled_at == expect and j.created_at == expect and j.updated_at == expect
        assert j.retry_at == expect                       # сервер был в UTC
        assert s.get(AppSettings, 1).clock_tz == settings.timezone
    assert clock.migrate_stored_times() == 0              # второй раз — ничего


# ------------------------------------------------------------- 3. Описание

@pytest.mark.parametrize("caption,typed,ok", [
    ("Смотри до конца #рек #fyp", "Смотри до конца  рек  fyp", True),
    ("Смотри до конца #рек", "", False),
    ("Смотри до конца", "video_123.mp4", False),
    ("", "что угодно", True),
])
def test_caption_typed(caption, typed, ok):
    from app.services.uploaders.tiktok import caption_typed

    assert caption_typed(caption, typed) is ok


# ------------------------------------------------------------- 4. Вход без сессии

def test_session_cookie_detection():
    from app.services.uploaders.base import has_session_cookie

    assert has_session_cookie({"cookies": [{"name": "sessionid", "value": "x", "domain": ".tiktok.com"}]})
    assert not has_session_cookie({"cookies": [{"name": "ttwid", "value": "x", "domain": ".tiktok.com"}]})
    assert not has_session_cookie({"cookies": [{"name": "sessionid", "value": "", "domain": ".tiktok.com"}]})
    assert not has_session_cookie(None)


def test_login_without_session_keeps_old_cookies(client, db, tmp_path):
    from types import SimpleNamespace

    from app.services import auto_login
    from app.services.uploaders.base import UploadError

    old = tmp_path / "old.json"
    old.write_text('{"cookies": []}', encoding="utf-8")
    acc = _account(db, cookies_path=str(old))
    ctx = SimpleNamespace(storage_state=lambda: {"cookies": [{"name": "ttwid", "value": "1",
                                                              "domain": ".tiktok.com"}]})
    with pytest.raises(UploadError, match="сессию не выдал"):
        auto_login._finish(acc, db, ctx)
    db.refresh(acc)
    assert acc.cookies_path == str(old) and old.exists()


# ------------------------------------------------------------- 5. Автомиграция

def test_function_default_is_not_a_string_literal():
    from app.db import _default_sql
    from app.models import Job as J

    sql, constant = _default_sql(J.__table__.c.created_at)
    assert sql == "CURRENT_TIMESTAMP" and constant is False


def test_added_timestamp_column_stays_readable(temp_db):
    import app.db as dbmod
    from app.models import Hook

    with temp_db.begin() as c:
        c.execute(text("INSERT INTO hooks (name, filename) VALUES ('h', 'h.mp4')"))
        c.execute(text("ALTER TABLE hooks DROP COLUMN created_at"))
    dbmod._auto_migrate()
    with sessionmaker(bind=temp_db)() as s:
        row = s.query(Hook).one()                           # раньше — ValueError: 'now()'
        assert isinstance(row.created_at, datetime)


# ------------------------------------------------------------- 6. Занятый аккаунт

def test_login_and_delete_refused_while_posting(client, db):
    import app.scheduler as sch

    acc = _account(db, tt_login="u", tt_password_enc="p")
    with sch._activity_lock:
        sch._posting_busy.add(acc.id)
    try:
        assert client.post(f"/api/accounts/{acc.id}/login/auto").status_code == 409
        assert client.delete(f"/api/accounts/{acc.id}").status_code == 409
    finally:
        with sch._activity_lock:
            sch._posting_busy.discard(acc.id)
    assert db.get(Account, acc.id) is not None


def test_account_delete_keeps_stats(client, db):
    acc, vid = _account(db), _video(db)
    db.add(Job(account_id=acc.id, video_id=vid.id, status=JobStatus.done)); db.commit()
    acc_id = acc.id
    assert client.delete(f"/api/accounts/{acc_id}").status_code == 200
    db.expunge_all()
    assert db.query(Job).filter(Job.account_id == acc_id).count() == 0
    assert sum(r.done for r in db.query(JobStat).filter(JobStat.account_id == acc_id)) == 1


# ------------------------------------------------------------- мелочи

@pytest.mark.parametrize("tpl,out", [
    ("Часть {n}/{total}", "Часть 2/5"),
    ("Часть {N}", "Часть {N}"),
    ("{n.__class__}", "{n.__class__}"),
])
def test_part_label(tpl, out):
    from app.services.posting import part_label

    assert part_label(tpl, 2, 5) == out


def _series(db, statuses):
    acc, vid = _account(db), _video(db)
    gid = uuid.uuid4().hex[:12]
    jobs = []
    for i, (st, kw) in enumerate(statuses, start=1):
        j = Job(account_id=acc.id, video_id=vid.id, status=st, group_id=gid,
                part_index=i, part_total=len(statuses), **kw)
        db.add(j); jobs.append(j)
    db.commit()
    return jobs


def test_series_part_waits_for_previous(client, db):
    from app.services.runner import series_blocker

    p1, p2 = _series(db, [(JobStatus.failed, {"error": "прокси", "log": "x"}),
                          (JobStatus.pending, {})])
    assert series_blocker(db, p2) == p1                     # часть 1 ещё повторится
    p1.attempts = 5; db.commit()
    assert series_blocker(db, p2) is None                   # повторов не будет — идём
    q1, q2 = _series(db, [(JobStatus.done, {}), (JobStatus.pending, {})])
    assert series_blocker(db, q2) is None


def test_auto_login_start_is_atomic(monkeypatch):
    from app.services import auto_login
    from app.services.uploaders.base import UploadError

    monkeypatch.setattr(auto_login, "_run", lambda _id: None)
    auto_login._state.pop(4242, None)
    wins, barrier = [], threading.Barrier(10)

    def go():
        barrier.wait()
        try:
            auto_login.start(4242)
            wins.append(1)
        except UploadError:
            pass

    ts = [threading.Thread(target=go) for _ in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1
    auto_login._state.pop(4242, None)


def test_emulator_screenshots_are_cleaned(client):
    import app.scheduler as sch

    settings.ensure_dirs()
    path = os.path.join(settings.output_dir, "emu_post_deadbeef.png")
    with open(path, "wb") as f:
        f.write(b"png")
    old = time.time() - 60 * 86400
    os.utime(path, (old, old))
    sch._cleanup_output()
    assert not os.path.exists(path)
