"""Очередь: автоповтор ошибок, уборка выполненных со счётчиком, массовый перезапуск."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Job, JobStat, JobStatus, Platform, Video
from app.services import retry


@pytest.fixture
def db(client):
    """client нужен ради init_db(): без него таблиц в тестовой базе нет."""
    s = SessionLocal()
    yield s
    s.close()


def _fixture(db, status=JobStatus.failed, error="сеть моргнула", *, attempts=0,
             days_old=0, output=None, log=""):
    acc = db.query(Account).first()
    if acc is None:
        acc = Account(name="очередь", platform=Platform.tiktok)
        db.add(acc); db.commit(); db.refresh(acc)
    vid = db.query(Video).first()
    if vid is None:
        vid = Video(title="v", filename="v.mp4")
        db.add(vid); db.commit(); db.refresh(vid)
    job = Job(account_id=acc.id, video_id=vid.id, status=status, error=error,
              attempts=attempts, output_filename=output, log=log)
    db.add(job); db.commit(); db.refresh(job)
    if days_old:
        stamp = datetime.now() - timedelta(days=days_old)
        db.query(Job).filter(Job.id == job.id).update(
            {"created_at": stamp, "updated_at": stamp}, synchronize_session=False)
        db.commit(); db.refresh(job)
    return job


# ----------------------------------------------------------------- политика

def test_retry_schedule_is_5_10_15_30_60():
    mins = [retry.retry_delay(i).total_seconds() // 60 for i in range(5)]
    assert mins == [5, 10, 15, 30, 60]
    assert retry.retry_delay(5) is None                 # шестой попытки нет
    assert retry.MAX_ATTEMPTS == 5


@pytest.mark.parametrize("error", [
    "Файл видео отсутствует", "Видео не найдено", "аккаунт выключен",
    "Не найден бинарник: ffmpeg",
])
def test_fatal_errors_are_not_retried(error):
    assert not retry.is_retryable(error)


@pytest.mark.parametrize("error", [
    "TikTok перекинул на страницу входа — куки недействительны",   # автологин может помочь
    "net::ERR_CONNECTION_RESET", "Timeout 60000ms exceeded", None,
])
def test_transient_errors_are_retried(error):
    assert retry.is_retryable(error)


# ----------------------------------------------------------------- планировщик

def test_fresh_failure_gets_retry_time(db):
    from app.scheduler import _schedule_retries

    job = _fixture(db)
    now = datetime(2026, 9, 17, 12, 0)
    _schedule_retries(db, now)
    db.refresh(job)
    assert job.status == JobStatus.failed
    assert job.retry_at == now + timedelta(minutes=5)
    assert "Повтор 1 из 5" in job.log


def test_due_retry_returns_job_to_queue(db):
    from app.scheduler import _schedule_retries

    job = _fixture(db, attempts=1)
    job.retry_at = datetime(2026, 9, 17, 12, 0)
    db.commit()
    _schedule_retries(db, datetime(2026, 9, 17, 12, 1))
    db.refresh(job)
    assert job.status == JobStatus.pending
    assert job.attempts == 2
    assert job.retry_at is None and job.error is None


def test_exhausted_job_stays_failed(db):
    from app.scheduler import _schedule_retries

    job = _fixture(db, attempts=5)
    _schedule_retries(db, datetime.now())
    db.refresh(job)
    assert job.status == JobStatus.failed and job.retry_at is None


def test_fatal_error_is_marked_and_never_retried(db):
    from app.scheduler import _schedule_retries

    job = _fixture(db, error="Файл видео отсутствует")
    _schedule_retries(db, datetime.now())
    db.refresh(job)
    assert job.retry_at is None
    assert job.attempts == retry.MAX_ATTEMPTS
    assert "требует вмешательства" in job.log


# ----------------------------------------------------------------- уборка

def _stat(db, account_id):
    return db.query(JobStat).filter(JobStat.account_id == account_id).all()


def test_old_done_job_goes_to_counter_with_files(db):
    from app.scheduler import _archive_old_jobs

    settings.ensure_dirs()
    open(os.path.join(settings.output_dir, "job_old.mp4"), "wb").close()
    open(os.path.join(settings.output_dir, "tiktok_result_777.png"), "wb").close()
    job = _fixture(db, JobStatus.done, None, days_old=5, output="job_old.mp4",
                   log="скриншот: tiktok_result_777.png")
    acc_id, day = job.account_id, job.created_at.date()

    removed = _archive_old_jobs()
    assert removed >= 1
    db.expunge_all()
    assert db.query(Job).filter(Job.id == job.id).first() is None
    row = next(r for r in _stat(db, acc_id) if r.day == day)
    assert row.done >= 1
    assert not os.path.exists(os.path.join(settings.output_dir, "job_old.mp4"))
    assert not os.path.exists(os.path.join(settings.output_dir, "tiktok_result_777.png"))


def test_fresh_done_and_any_failed_survive_cleanup(db):
    from app.scheduler import _archive_old_jobs

    fresh_id = _fixture(db, JobStatus.done, None, days_old=1).id
    failed_id = _fixture(db, JobStatus.failed, "ошибка", days_old=30).id
    _archive_old_jobs()
    db.expunge_all()
    assert db.query(Job).filter(Job.id == fresh_id).first() is not None
    assert db.query(Job).filter(Job.id == failed_id).first() is not None


def test_manual_delete_of_failed_counts_it(client, db):
    job = _fixture(db, JobStatus.failed, "ошибка")
    acc_id, day = job.account_id, job.created_at.date()
    before = sum(r.failed for r in _stat(db, acc_id) if r.day == day)
    assert client.delete(f"/api/jobs/{job.id}").status_code == 200
    db.expunge_all()
    after = sum(r.failed for r in _stat(db, acc_id) if r.day == day)
    assert after == before + 1


def test_manual_delete_of_pending_is_not_counted(client, db):
    job = _fixture(db, JobStatus.pending, None)
    acc_id = job.account_id
    before = sum(r.done + r.failed for r in _stat(db, acc_id))
    assert client.delete(f"/api/jobs/{job.id}").status_code == 200
    db.expunge_all()
    assert sum(r.done + r.failed for r in _stat(db, acc_id)) == before


# ----------------------------------------------------------------- API

def test_retry_failed_restarts_everything(client, db, monkeypatch):
    import app.routers.jobs as jobs_router

    monkeypatch.setattr(jobs_router, "submit_job", lambda _id: None)   # без Playwright
    ids = [_fixture(db, JobStatus.failed, "x", attempts=3).id,
           _fixture(db, JobStatus.failed, "y", attempts=5).id]
    r = client.post("/api/jobs/retry-failed")
    assert r.status_code == 200 and r.json()["restarted"] >= 2
    db.expunge_all()
    for jid in ids:
        j = db.query(Job).filter(Job.id == jid).first()
        assert j.status == JobStatus.pending
        assert j.attempts == 0 and j.retry_at is None and j.error is None


def test_stats_archive_endpoint(client, db):
    job = _fixture(db, JobStatus.done, None)
    assert client.delete(f"/api/jobs/{job.id}").status_code == 200
    rows = client.get("/api/stats/archive").json()
    assert any(r["account_id"] == job.account_id and r["done"] >= 1 for r in rows)


def test_job_out_exposes_retry_fields(client, db):
    job = _fixture(db, JobStatus.failed, "x", attempts=2)
    body = next(j for j in client.get("/api/jobs").json() if j["id"] == job.id)
    assert body["attempts"] == 2 and "retry_at" in body
