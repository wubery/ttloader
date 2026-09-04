"""Удаление видео с задачами и устойчивая заливка.

Регрессии, которые чинятся здесь:
* удалить ролик, на который есть задача, было нельзя вовсе — БД роняла запрос
  на NOT NULL constraint failed: jobs.video_id, панель показывала 500;
* оборванная заливка оставляла в библиотеке обрезанный файл.
"""
from __future__ import annotations

import io
import os

import pytest

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Job, JobStatus, Platform, Video


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def _video(db, title: str) -> Video:
    settings.ensure_dirs()
    v = Video(title=title, filename=f"{title}.mp4")
    db.add(v)
    db.commit()
    db.refresh(v)
    open(os.path.join(settings.videos_dir, v.filename), "wb").close()
    return v


def _job(db, video: Video, output: str | None = None) -> Job:
    acc = db.query(Account).first()
    if acc is None:
        acc = Account(name="для задач", platform=Platform.tiktok)
        db.add(acc)
        db.commit()
        db.refresh(acc)
    job = Job(account_id=acc.id, video_id=video.id, status=JobStatus.done,
              output_filename=output)
    db.add(job)
    db.commit()
    return job


def test_delete_plain_video(client, db):
    v = _video(db, "без задач")
    assert client.delete(f"/api/videos/{v.id}").status_code == 200
    assert not os.path.exists(os.path.join(settings.videos_dir, "без задач.mp4"))


def test_delete_video_with_jobs_asks_first(client, db):
    v = _video(db, "с задачами")
    _job(db, v)
    _job(db, v)
    r = client.delete(f"/api/videos/{v.id}")
    assert r.status_code == 409                      # раньше здесь была пятисотка
    assert "2" in r.json()["detail"]                 # сколько задач мешает
    db.expire_all()
    assert db.get(Video, v.id) is not None           # без подтверждения ничего не тронуто


def test_force_deletes_video_with_jobs_and_renders(client, db):
    v = _video(db, "с рендером")
    rendered = os.path.join(settings.output_dir, "job_render.mp4")
    open(rendered, "wb").close()
    _job(db, v, output="job_render.mp4")

    r = client.delete(f"/api/videos/{v.id}?force=true")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_jobs"] == 1
    vid = v.id
    db.expunge_all()                                 # иначе get() поднимет ObjectDeletedError
    assert db.query(Video).filter(Video.id == vid).first() is None
    assert db.query(Job).filter(Job.video_id == vid).count() == 0
    assert not os.path.exists(rendered)              # отрендеренный файл тоже убран


def test_upload_rejects_unknown_extension(client):
    r = client.post("/api/videos", files={"file": ("x.txt", io.BytesIO(b"1"), "text/plain")})
    assert r.status_code == 400


def test_upload_saves_file_and_leaves_no_part(client):
    r = client.post("/api/videos",
                    files={"file": ("клип.mp4", io.BytesIO(b"0" * 4096), "video/mp4")})
    assert r.status_code == 200, r.text
    name = r.json()["filename"]
    assert os.path.exists(os.path.join(settings.videos_dir, name))
    leftovers = [f for f in os.listdir(settings.videos_dir) if f.endswith(".part")]
    assert leftovers == []                           # временный файл переименован, не брошен


def test_no_space_reported_as_507(client, monkeypatch):
    """Кончившееся место должно быть внятной ошибкой, а не обрывом соединения."""
    from app.services import storage

    monkeypatch.setattr(storage, "free_space", lambda p: (1024, 10 * 1024))
    r = client.post("/api/videos",
                    files={"file": ("большой.mp4", io.BytesIO(b"0" * 200000), "video/mp4")})
    assert r.status_code == 507
    assert "мест" in r.json()["detail"].lower()


def test_health_reports_free_space(client):
    body = client.get("/api/health").json()
    assert body["disk_total"] and body["disk_free"] <= body["disk_total"]
