"""Критичные пункты аудита: перебор входа, прерванные задачи, дубли при повторе,
резервные копии, WAL."""
from __future__ import annotations

import os
import tarfile
from datetime import datetime

import pytest

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Account, Job, JobStatus, Platform, Video
from app.services import backup, ratelimit, retry


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _clean_limiter():
    ratelimit._fails.clear()
    ratelimit._trusted.clear()
    yield
    ratelimit._fails.clear()
    ratelimit._trusted.clear()


# ------------------------------------------------------------- перебор входа

def test_limiter_blocks_after_five_failures():
    now = 1000.0
    for _ in range(ratelimit.PER_KEY):
        assert ratelimit.retry_after("1.2.3.4", now) == 0
        ratelimit.fail("1.2.3.4", now)
    assert ratelimit.retry_after("1.2.3.4", now) > 0
    assert ratelimit.retry_after("5.6.7.8", now) == 0          # чужой адрес не страдает


def test_limiter_window_expires():
    for _ in range(ratelimit.PER_KEY):
        ratelimit.fail("1.2.3.4", 1000.0)
    assert ratelimit.retry_after("1.2.3.4", 1000.0 + ratelimit.WINDOW + 1) == 0


def test_global_limit_stops_distributed_bruteforce():
    """Перебор с разных адресов (или с подделанным заголовком) упирается в общий лимит."""
    for i in range(ratelimit.GLOBAL):
        ratelimit.fail(f"10.0.0.{i}", 1000.0)
    assert ratelimit.retry_after("192.168.9.9", 1000.0) > 0


def test_login_endpoint_returns_429(client):
    for _ in range(ratelimit.PER_KEY):
        r = client.post("/api/auth/login", json={"username": "test", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "test", "password": "wrong"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # даже верный пароль не пускает, пока адрес в блоке
    r = client.post("/api/auth/login", json={"username": "test", "password": "test-pass"})
    assert r.status_code == 429


def test_successful_login_resets_counter(client):
    for _ in range(ratelimit.PER_KEY - 1):
        client.post("/api/auth/login", json={"username": "test", "password": "wrong"})
    assert client.post("/api/auth/login",
                       json={"username": "test", "password": "test-pass"}).status_code == 200
    assert client.post("/api/auth/login",
                       json={"username": "test", "password": "wrong"}).status_code == 401


def test_telegram_codes_burn_after_failures():
    from app.services import telegram

    telegram._login_codes.clear()
    telegram._login_codes["123456"] = 9e12
    for _ in range(telegram.MAX_CODE_FAILURES):
        assert not telegram.check_login_code("000000")
    assert not telegram.check_login_code("123456")             # настоящий код сгорел


def test_session_cookie_secure_only_over_https(client):
    r = client.post("/api/auth/login", json={"username": "test", "password": "test-pass"},
                    headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers.get("set-cookie", "").lower()
    r = client.post("/api/auth/login", json={"username": "test", "password": "test-pass"})
    assert "secure" not in r.headers.get("set-cookie", "").lower()


# ------------------------------------------------------------- прерванные задачи

def _job(db, status):
    acc = db.query(Account).first() or Account(name="h", platform=Platform.tiktok)
    vid = db.query(Video).first() or Video(title="v", filename="v.mp4")
    db.add_all([acc, vid]); db.commit()
    job = Job(account_id=acc.id, video_id=vid.id, status=status)
    db.add(job); db.commit(); db.refresh(job)
    return job.id


def test_interrupted_jobs_become_failed_on_startup(db):
    from app.main import _recover_interrupted_jobs

    rid, uid, pid = (_job(db, JobStatus.rendering), _job(db, JobStatus.uploading),
                     _job(db, JobStatus.pending))
    _recover_interrupted_jobs()
    db.expire_all()
    for jid in (rid, uid):
        j = db.get(Job, jid)
        assert j.status == JobStatus.failed and "перезапуском" in j.error
    assert db.get(Job, pid).status == JobStatus.pending        # ожидающие не трогаем


# ------------------------------------------------------------- дубли при повторе

def test_no_auto_retry_after_publish_click():
    log = "[10:00] Заливаю…\n[10:02] Публикую…\n[10:03] Не дождался подтверждения"
    when, why = retry.schedule_retry_for("таймаут", log, 0, datetime.now())
    assert when is None and "могла пройти" in why


def test_earlier_attempt_publish_does_not_block():
    """Учитывается только последняя попытка: прошлые «Публикую…» не в счёт."""
    log = "Публикую…\nошибка\nАвтоповтор 1 из 5.\n[11:00] Заливаю…\nсеть упала"
    assert not retry.publish_attempted(log)
    when, _ = retry.schedule_retry_for("сеть упала", log, 1, datetime.now())
    assert when is not None


def test_failure_before_publish_is_retried():
    when, _ = retry.schedule_retry_for("сеть", "[10:00] Заливаю…", 0, datetime.now())
    assert when is not None


# ------------------------------------------------------------- резервные копии

def test_backup_contains_db_and_cookies(client):
    settings.ensure_dirs()
    with open(os.path.join(settings.cookies_dir, "acc_test.json"), "w") as f:
        f.write("{}")
    name = backup.make_backup()
    path = backup.backup_path(name)
    with tarfile.open(path) as tar:
        names = tar.getnames()
    assert "video_poster.db" in names
    assert any(n.startswith("cookies/") for n in names)


def test_backup_rotation_keeps_last(client, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_KEEP", 2)
    d = backup.backups_dir()
    for i in range(4):
        open(os.path.join(d, f"vp-2020010{i + 1}-000000.tar.gz"), "wb").close()
    backup._rotate()
    assert len(backup.list_backups()) == 2


@pytest.mark.parametrize("name", ["../video_poster.db", "vp-1.tar.gz", "secret.key", ""])
def test_backup_name_is_validated(name):
    assert backup.backup_path(name) is None


def test_backup_api(client):
    r = client.post("/api/system/backups")
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert any(b["name"] == name for b in client.get("/api/system/backups").json())
    assert client.get(f"/api/system/backups/{name}").status_code == 200
    assert client.get("/api/system/backups/..%2Fvideo_poster.db").status_code == 404


# ------------------------------------------------------------- WAL

def test_sqlite_runs_in_wal(client):
    with engine.connect() as c:
        mode = c.exec_driver_sql("PRAGMA journal_mode").scalar()
    assert str(mode).lower() == "wal"
