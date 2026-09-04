"""Заливка кусками: обходит чужой прокси с лимитом на размер тела запроса."""
from __future__ import annotations

import io
import os

from app.config import settings
from app.services import storage


def _chunk(client, upload_id: str, index: int, data: bytes, name: str = "часть.mp4"):
    return client.post("/api/videos/chunk",
                       data={"upload_id": upload_id, "index": str(index)},
                       files={"file": (name, io.BytesIO(data), "video/mp4")})


def test_chunks_assemble_into_one_file(client):
    uid = "a" * 16
    parts = [b"1" * 1000, b"2" * 1000, b"3" * 500]
    for i, p in enumerate(parts):
        r = _chunk(client, uid, i, p)
        assert r.status_code == 200, r.text
    assert r.json()["received"] == 2500                # накопленный размер растёт

    r = client.post("/api/videos/chunk/finish",
                    json={"upload_id": uid, "filename": "длинный ролик.mp4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "длинный ролик"
    saved = os.path.join(settings.videos_dir, body["filename"])
    assert open(saved, "rb").read() == b"".join(parts)  # порядок кусков сохранён
    assert not os.path.exists(storage.part_path(settings.videos_dir, uid))


def test_index_zero_restarts_upload(client):
    """Повтор с нуля не должен дописываться к прошлой попытке."""
    uid = "b" * 16
    _chunk(client, uid, 0, b"x" * 100)
    _chunk(client, uid, 1, b"x" * 100)
    r = _chunk(client, uid, 0, b"y" * 50)
    assert r.json()["received"] == 50


def test_bad_upload_id_rejected(client):
    r = _chunk(client, "../../etc/passwd", 0, b"1")
    assert r.status_code == 400                        # id подставляется в имя файла


def test_finish_checks_extension(client):
    uid = "c" * 16
    _chunk(client, uid, 0, b"1" * 10)
    r = client.post("/api/videos/chunk/finish", json={"upload_id": uid, "filename": "x.txt"})
    assert r.status_code == 400
    assert not os.path.exists(storage.part_path(settings.videos_dir, uid))  # мусор убран


def test_finish_without_chunks_is_404(client):
    r = client.post("/api/videos/chunk/finish",
                    json={"upload_id": "d" * 16, "filename": "x.mp4"})
    assert r.status_code == 404


def test_abort_removes_partial_file(client):
    uid = "e" * 16
    _chunk(client, uid, 0, b"1" * 100)
    assert client.delete(f"/api/videos/chunk/{uid}").status_code == 200
    assert not os.path.exists(storage.part_path(settings.videos_dir, uid))


def test_cleanup_removes_only_stale_parts(client, monkeypatch):
    fresh, old = "f" * 16, "0" * 16
    _chunk(client, fresh, 0, b"1" * 10)
    _chunk(client, old, 0, b"1" * 10)
    stale_path = storage.part_path(settings.videos_dir, old)
    os.utime(stale_path, (0, 0))                       # как будто брошен давно

    assert storage.cleanup_stale_parts(settings.videos_dir) == 1
    assert not os.path.exists(stale_path)
    assert os.path.exists(storage.part_path(settings.videos_dir, fresh))


def test_no_space_stops_chunk_upload(client, monkeypatch):
    monkeypatch.setattr(storage, "free_space", lambda p: (1024, 10 * 1024))
    r = _chunk(client, "9" * 16, 0, b"1" * 100)
    assert r.status_code == 507


def test_upload_probe_reports_received_size(client):
    """Проба канала: сервер отвечает, сколько байт до него реально дошло."""
    r = client.post("/api/system/upload-probe",
                    files={"file": ("probe.bin", io.BytesIO(b"0" * 3000), "application/octet-stream")})
    assert r.status_code == 200, r.text
    assert r.json()["received"] == 3000


def test_upload_probe_saves_nothing(client):
    before = set(os.listdir(settings.videos_dir))
    client.post("/api/system/upload-probe",
                files={"file": ("probe.bin", io.BytesIO(b"0" * 1000), "application/octet-stream")})
    assert set(os.listdir(settings.videos_dir)) == before
