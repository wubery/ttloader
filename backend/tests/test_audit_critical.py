"""Аудит, критичное и важное: бот без chat_id, дубли постов, удаление,
один браузер на аккаунт, смена пароля, блокировка входа."""
from __future__ import annotations

import json
import os
import uuid

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Banner, BannerType, Job, JobStatus, Platform, Video
from app.services import ratelimit, retry


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


def _account(db, **kw) -> Account:
    acc = Account(name=f"audit_{uuid.uuid4().hex[:6]}", platform=Platform.tiktok, **kw)
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _video(db, with_file: bool = False) -> Video:
    fname = f"audit_{uuid.uuid4().hex[:8]}.mp4"
    if with_file:
        settings.ensure_dirs()
        with open(os.path.join(settings.videos_dir, fname), "wb") as f:
            f.write(b"x")
    v = Video(title="audit", filename=fname)
    db.add(v); db.commit(); db.refresh(v)
    return v


def _job(db, acc=None, vid=None, **kw) -> Job:
    acc = acc or _account(db)
    vid = vid or _video(db)
    job = Job(account_id=acc.id, video_id=vid.id, **kw)
    db.add(job); db.commit(); db.refresh(job)
    return job


# ------------------------------------------------------------- 1. Telegram-бот

@pytest.fixture
def sent(monkeypatch):
    from app.services import telegram

    out: list[tuple[str, str]] = []
    monkeypatch.setattr(telegram, "send_message",
                        lambda tok, cid, text, reply_markup=None: out.append((cid, text)))
    return out


def _msg(chat_id: int, text: str, kind: str = "private") -> dict:
    return {"update_id": 1, "message": {"chat": {"id": chat_id, "type": kind}, "text": text}}


def test_bot_without_chat_ids_obeys_nobody(client, sent, monkeypatch):
    from app.services import telegram

    called = []
    monkeypatch.setattr(telegram, "_cmd_newpost", lambda *a: called.append(a))
    for cmd in ("/settings", "/queue", "/newpost all 1 x", "/delete video 1"):
        telegram._handle_update("TOKEN", [], _msg(555, cmd))
    assert sent == [] and called == []


def test_bot_tells_stranger_his_chat_id_on_start_only(client, sent):
    from app.services import telegram

    telegram._handle_update("TOKEN", [], _msg(555, "/start"))
    assert len(sent) == 1 and "555" in sent[0][1] and "/queue" not in sent[0][1]
    telegram._handle_update("TOKEN", ["1"], _msg(-100, "/start", kind="group"))
    assert len(sent) == 1                       # в группах молчим совсем


def test_bot_serves_allowed_chat(client, sent):
    from app.services import telegram

    telegram._handle_update("TOKEN", ["555"], _msg(555, "/settings"))
    assert sent and sent[0][0] == "555"


def test_bot_ignores_callbacks_without_chat_ids(client, sent, monkeypatch):
    from app.services import telegram

    monkeypatch.setattr(telegram, "_api", lambda *a, **k: {})
    upd = {"update_id": 2, "callback_query": {"id": "1", "data": "refresh_queue",
                                              "message": {"chat": {"id": 555}}}}
    telegram._handle_update("TOKEN", [], upd)
    assert sent == []


# ------------------------------------------------------------- 2. Дубли постов

def test_retry_failed_skips_maybe_published(client, db, monkeypatch):
    import app.routers.jobs as jr

    submitted: list[int] = []
    monkeypatch.setattr(jr, "submit_job", submitted.append)
    risky = _job(db, status=JobStatus.failed, error="не подтвердил", log="[1] Публикую…\n")
    safe = _job(db, status=JobStatus.failed, error="прокси", log="[1] Открываю страницу\n")
    r = client.post("/api/jobs/retry-failed").json()
    assert safe.id in submitted and risky.id not in submitted
    assert r["skipped_maybe_posted"] >= 1
    db.expire_all()
    assert db.get(Job, risky.id).status == JobStatus.failed


def test_single_retry_of_maybe_published_needs_force(client, db, monkeypatch):
    import app.routers.jobs as jr

    monkeypatch.setattr(jr, "submit_job", lambda _id: None)
    job = _job(db, status=JobStatus.failed, error="не подтвердил", log="Публикую…\n")
    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 409
    r = client.post(f"/api/jobs/{job.id}/retry?force=true")
    assert r.status_code == 200 and r.json()["status"] == "pending"


def test_retry_of_done_job_needs_force(client, db, monkeypatch):
    import app.routers.jobs as jr

    monkeypatch.setattr(jr, "submit_job", lambda _id: None)
    job = _job(db, status=JobStatus.done)
    assert client.post(f"/api/jobs/{job.id}/retry").status_code == 409


def test_manual_retry_starts_a_fresh_attempt_in_log(client, db, monkeypatch):
    """После ручного перезапуска старая метка «Публикую…» не должна отключать
    автоповтор, если новая попытка упала ещё до публикации."""
    import app.routers.jobs as jr

    monkeypatch.setattr(jr, "submit_job", lambda _id: None)
    job = _job(db, status=JobStatus.failed, error="x", log="Публикую…\n")
    client.post(f"/api/jobs/{job.id}/retry?force=true")
    db.expire_all()
    log = db.get(Job, job.id).log + "[2] Ошибка прокси\n"
    assert not retry.publish_attempted(log)
    assert retry.publish_attempted(log + "Публикую…\n")


def test_success_survives_error_after_publish(client, db, monkeypatch):
    """Ролик выложен — ошибка на сохранении ника не делает задачу упавшей."""
    from app.services import runner
    from app.services.uploaders.base import UploadResult

    acc = _account(db, uniqueize=False)
    job = _job(db, acc=acc, status=JobStatus.pending)
    monkeypatch.setattr(runner, "_ensure_session", lambda *a: True)
    monkeypatch.setattr(runner, "get_uploader", lambda _p: lambda **kw: UploadResult(
        ok=True, url="https://www.tiktok.com/@a/video/1", handle="a"))

    def boom(*_a):
        raise RuntimeError("БД занята")

    monkeypatch.setattr(runner, "_remember_handle", boom)
    runner.run_job(job.id)
    db.expire_all()
    j = db.get(Job, job.id)
    assert j.status == JobStatus.done and j.posted_url


# ------------------------------------------------------------- 3. Удаление

def test_bot_delete_video_with_jobs_keeps_everything(client, db, sent):
    from app.services import telegram

    vid = _video(db, with_file=True)
    _job(db, vid=vid, status=JobStatus.pending)
    vid_id, path = vid.id, os.path.join(settings.videos_dir, vid.filename)
    telegram._cmd_delete("TOKEN", "1", f"/delete video {vid_id}")
    db.expire_all()
    assert db.get(Video, vid_id) is not None and os.path.exists(path)
    assert "force" in sent[-1][1]

    telegram._cmd_delete("TOKEN", "1", f"/delete video {vid_id} force")
    db.expunge_all()
    assert db.get(Video, vid_id) is None and not os.path.exists(path)
    assert db.query(Job).filter(Job.video_id == vid_id).count() == 0


def test_running_job_blocks_video_and_job_delete(client, db, sent):
    from app.services import telegram

    vid = _video(db, with_file=True)
    job = _job(db, vid=vid, status=JobStatus.uploading)
    assert client.delete(f"/api/videos/{vid.id}?force=true").status_code == 400
    assert client.delete(f"/api/jobs/{job.id}").status_code == 400
    telegram._cmd_delete("TOKEN", "1", f"/delete job {job.id}")
    db.expire_all()
    assert db.get(Job, job.id) is not None and "выполняется" in sent[-1][1]


def _banner(db) -> Banner:
    b = Banner(name="audit", type=BannerType.image, filename=f"audit_{uuid.uuid4().hex[:8]}.png")
    db.add(b); db.commit(); db.refresh(b)
    return b


def test_banner_of_pending_job_needs_force(client, db):
    b = _banner(db)
    job = _job(db, status=JobStatus.pending, banner_id=b.id)
    assert client.delete(f"/api/banners/{b.id}").status_code == 409
    r = client.delete(f"/api/banners/{b.id}?force=true")
    assert r.status_code == 200 and r.json()["affected_jobs"] == 1
    db.expire_all()
    assert db.get(Job, job.id).banner_id is None


def test_banner_in_editor_layers_counts_too(client, db):
    b = _banner(db)
    _job(db, status=JobStatus.pending, overlays=json.dumps([{"type": "banner", "banner_id": b.id}]))
    assert client.delete(f"/api/banners/{b.id}").status_code == 409


def test_banner_of_finished_jobs_deletes_freely(client, db):
    b = _banner(db)
    _job(db, status=JobStatus.done, banner_id=b.id)
    assert client.delete(f"/api/banners/{b.id}").status_code == 200


# ------------------------------------------------------------- 4. Один браузер на аккаунт

class _SyncExecutor:
    def submit(self, fn):
        fn()


def test_posting_waits_while_account_busy(client, db, monkeypatch):
    import app.scheduler as sch

    ran: list[int] = []
    monkeypatch.setattr(sch, "_executor", _SyncExecutor())
    monkeypatch.setattr(sch, "run_job", ran.append)
    job = _job(db, status=JobStatus.pending)

    sch._activity_busy.add(job.account_id)          # идёт лента/лайки
    try:
        sch.submit_job(job.id)
        sch.submit_job(job.id)
    finally:
        sch._activity_busy.discard(job.account_id)
    assert ran == []
    db.expire_all()
    assert db.get(Job, job.id).log.count(sch.BUSY_NOTE) == 1   # причина — один раз

    sch.submit_job(job.id)                          # аккаунт освободился
    assert ran == [job.id] and job.account_id not in sch._posting_busy


def test_second_post_of_same_account_waits(client, db):
    import app.scheduler as sch

    acc = _account(db)
    assert sch._claim_for_posting(acc.id)
    try:
        assert not sch._claim_for_posting(acc.id)
        assert sch._account_busy(acc.id)            # и активность его не тронет
    finally:
        with sch._activity_lock:
            sch._posting_busy.discard(acc.id)
    assert sch._claim_for_posting(acc.id)
    with sch._activity_lock:
        sch._posting_busy.discard(acc.id)


# ------------------------------------------------------------- 5. Смена пароля

def test_password_change_requires_current_and_revokes_sessions(client):
    from fastapi.testclient import TestClient

    from app.main import app

    ratelimit._fails.clear()
    old_cookie = client.cookies.get("vp_session")
    url = "/api/settings"
    assert client.post(url, json={"new_password": "new-pass-123"}).status_code == 403
    assert client.post(url, json={"new_password": "new-pass-123",
                                  "current_password": "wrong"}).status_code == 403
    assert client.post(url, json={"new_password": "short",
                                  "current_password": "test-pass"}).status_code == 400
    try:
        r = client.post(url, json={"new_password": "new-pass-123", "current_password": "test-pass"})
        assert r.status_code == 200
        assert client.get(url).status_code == 200          # текущей сессии выдана новая
        stale = TestClient(app)
        stale.cookies.set("vp_session", old_cookie)
        assert stale.get(url).status_code == 401           # старая — больше нет
    finally:
        client.post(url, json={"new_password": "test-pass", "current_password": "new-pass-123"})
        ratelimit._fails.clear()
    assert client.post("/api/auth/login", json={"username": "test", "password": "test-pass"}
                       ).status_code == 200


# ------------------------------------------------------------- 6. Блокировка входа

def test_global_lock_does_not_lock_out_known_owner():
    ratelimit._fails.clear()
    ratelimit._trusted.clear()
    try:
        ratelimit.reset("1.1.1.1", 1000.0)                 # владелец входил отсюда
        for i in range(ratelimit.GLOBAL):
            ratelimit.fail(f"10.9.0.{i}", 1000.0)
        assert ratelimit.retry_after("2.2.2.2", 1000.0) > 0    # чужим — общий блок
        assert ratelimit.retry_after("1.1.1.1", 1000.0) == 0   # владельцу — нет
        for _ in range(ratelimit.PER_KEY):
            ratelimit.fail("1.1.1.1", 1000.0)
        assert ratelimit.retry_after("1.1.1.1", 1000.0) > 0    # свой лимит остаётся
        later = 1000.0 + ratelimit.TRUST_TTL + ratelimit.WINDOW + 1
        for i in range(ratelimit.GLOBAL):
            ratelimit.fail(f"10.8.0.{i}", later)
        assert ratelimit.retry_after("1.1.1.1", later) > 0     # доверие истекает
    finally:
        ratelimit._fails.clear()
        ratelimit._trusted.clear()
