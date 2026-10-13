"""Важные пункты аудита: гонка захвата аккаунта, хвост лога в очереди,
версия браузера в User-Agent, шифрование токена бота."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.db import SessionLocal
from app.models import Account, AppSettings, Job, JobStatus, Platform, Video


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


def test_account_claim_is_atomic(client, monkeypatch):
    """Из множества одновременных попыток занять аккаунт проходит ровно одна."""
    import app.scheduler as sch

    monkeypatch.setattr(sch, "_account_busy", lambda aid: aid in sch._activity_busy)
    sch._activity_busy.clear()
    wins, barrier = [], threading.Barrier(20)

    def worker():
        barrier.wait()
        if sch._claim_account(777):
            wins.append(1)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(wins) == 1
    sch._release_account(777)
    assert 777 not in sch._activity_busy


def test_job_list_sends_log_tail_only(client, db):
    acc = db.query(Account).first() or Account(name="l", platform=Platform.tiktok)
    vid = db.query(Video).first() or Video(title="v", filename="v.mp4")
    db.add_all([acc, vid]); db.commit()
    big = "".join(f"[10:00] строка {i}\n" for i in range(2000)) + "tiktok_result_42.png\n"
    job = Job(account_id=acc.id, video_id=vid.id, status=JobStatus.failed, log=big)
    db.add(job); db.commit(); db.refresh(job)

    item = next(j for j in client.get("/api/jobs").json() if j["id"] == job.id)
    assert item["log_truncated"] is True
    assert len(item["log"]) <= 1500
    assert item["log"].endswith("tiktok_result_42.png\n")      # хвост сохранён
    assert item["has_screenshot"] is True                     # флаг считан по полному логу
    full = client.get(f"/api/jobs/{job.id}/log")
    assert full.status_code == 200 and full.text == big


def test_stored_log_is_capped():
    from app.services.runner import MAX_LOG_CHARS, _append_log

    job = SimpleNamespace(log="x" * (MAX_LOG_CHARS + 500))
    _append_log(job, "последняя")
    assert len(job.log) <= MAX_LOG_CHARS + 100
    assert job.log.rstrip().endswith("последняя")


def test_user_agent_follows_browser_engine():
    from app.services.uploaders.base import STEALTH_USER_AGENT, user_agent_for

    assert "Chrome/131.0.0.0" in user_agent_for(SimpleNamespace(version="131.0.6778.33"))
    assert user_agent_for(None) == STEALTH_USER_AGENT
    assert user_agent_for(SimpleNamespace(version="мусор")) == STEALTH_USER_AGENT


def test_bot_token_is_stored_encrypted(client, db):
    from app.services.crypto import PREFIX
    from app.services.telegram import _settings as _config

    r = client.post("/api/settings", json={"tg_bot_token": "123:SECRET"})
    assert r.status_code == 200 and r.json()["tg_bot_configured"] is True
    db.expire_all()
    raw = db.get(AppSettings, 1).tg_bot_token
    assert raw.startswith(PREFIX) and "SECRET" not in raw
    assert _config()[0] == "123:SECRET"                       # бот читает расшифрованным
    client.post("/api/settings", json={"tg_bot_token": ""})


def test_legacy_plain_token_is_migrated(client, db):
    from app.services.appsettings import bootstrap_settings
    from app.services.crypto import PREFIX

    row = db.get(AppSettings, 1)
    row.tg_bot_token = "999:PLAIN"
    db.commit()
    bootstrap_settings()
    db.expire_all()
    assert db.get(AppSettings, 1).tg_bot_token.startswith(PREFIX)
    db.get(AppSettings, 1).tg_bot_token = None
    db.commit()


def test_ad_file_and_delete_do_not_crash(client):
    """Регресс: в ads.py проверялась несуществующая переменная hook — любой
    запрос файла рекламы и удаление падали с NameError (500). Нашёл ruff F821."""
    assert client.get("/api/ads/999999/file").status_code == 404
    assert client.delete("/api/ads/999999").status_code == 404
