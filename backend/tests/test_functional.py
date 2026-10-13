"""Функциональные пункты аудита: квота постов и ротация подписей."""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from app.db import SessionLocal
from app.models import Account, AppSettings, Job, JobStat, JobStatus, Platform, Video
from app.services import caption


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


# ------------------------------------------------------------- ротация подписей

def test_spin_picks_one_variant():
    seen = {caption.spin("{Смотри|Глянь|Зацени} до конца", random.Random(i)) for i in range(60)}
    assert seen == {"Смотри до конца", "Глянь до конца", "Зацени до конца"}


def test_spin_handles_nesting():
    out = caption.spin("{a {x|y}|b}", random.Random(3))
    assert out in {"a x", "a y", "b"}


@pytest.mark.parametrize("text", ["Часть {n}/{total}", "просто {скобки}", "", "без вариантов #тег"])
def test_spin_leaves_plain_braces_alone(text):
    assert caption.spin(text) == text


def test_bulk_jobs_get_different_captions(client, db, monkeypatch):
    import app.scheduler as sch

    monkeypatch.setattr(sch, "submit_job", lambda _id: None)
    vid = Video(title="v", filename="v.mp4")
    accs = [Account(name=f"q{i}", platform=Platform.tiktok) for i in range(12)]
    db.add_all([vid, *accs]); db.commit()
    from app.services import posting

    monkeypatch.setattr(posting, "_skip_reason", lambda _db, _id: None)
    jobs, _ = posting.create_jobs(db, account_ids=[a.id for a in accs], video_id=vid.id,
                                  caption="{один|два|три|четыре}", spread_min=0, spread_max=0)
    caps = {j.caption for j in jobs}
    assert len(caps) > 1 and all(c in {"один", "два", "три", "четыре"} for c in caps)


# ------------------------------------------------------------- квота постов

def _set_quota(db, n):
    row = db.get(AppSettings, 1)
    row.posts_per_day_max = n
    db.commit()


def test_quota_counts_live_and_archived(db):
    from app.services.runner import posts_today

    acc = Account(name="quota", platform=Platform.tiktok)
    vid = db.query(Video).first() or Video(title="v", filename="v.mp4")
    db.add_all([acc, vid]); db.commit()
    db.add_all([Job(account_id=acc.id, video_id=vid.id, status=JobStatus.done) for _ in range(2)])
    db.add(JobStat(day=datetime.now().date(), account_id=acc.id, done=3))
    db.commit()
    assert posts_today(db, acc.id, datetime.now()) == 5


def test_job_over_quota_is_deferred_not_failed(db):
    from app.services.runner import run_job

    acc = Account(name="quota2", platform=Platform.tiktok)
    vid = db.query(Video).first() or Video(title="v", filename="v.mp4")
    db.add_all([acc, vid]); db.commit()
    db.add(Job(account_id=acc.id, video_id=vid.id, status=JobStatus.done)); db.commit()
    job = Job(account_id=acc.id, video_id=vid.id, status=JobStatus.pending)
    db.add(job); db.commit()
    jid = job.id
    _set_quota(db, 1)
    try:
        run_job(jid)
    finally:
        _set_quota(db, 0)
    db.expire_all()
    j = db.get(Job, jid)
    assert j.status == JobStatus.pending
    assert j.scheduled_at and j.scheduled_at.date() > datetime.now().date()
    assert "Квота" in j.log


def test_next_quota_slot_is_tomorrow_in_window():
    from app.services.runner import next_quota_slot

    now = datetime(2026, 10, 13, 22, 0)
    for i in range(30):
        t = next_quota_slot(now, 9, random.Random(i))
        assert t.date() == datetime(2026, 10, 14).date() and 9 <= t.hour <= 11


def test_quota_setting_is_validated(client):
    assert client.post("/api/activity/settings", json={"posts_per_day_max": 500}).status_code == 400
    r = client.post("/api/activity/settings", json={"posts_per_day_max": 3})
    assert r.status_code == 200 and r.json()["posts_per_day_max"] == 3
    client.post("/api/activity/settings", json={"posts_per_day_max": 0})
