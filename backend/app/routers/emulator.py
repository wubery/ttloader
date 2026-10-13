"""Вкладка «Эмулятор»: тестовая заливка через приложение TikTok по ADB.

Режим экспериментальный — см. services/emulator.py: «Опубликовать» не
нажимается, результат — снимок экрана и разбор того, где остановились.
"""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Video
from ..services import emulator

router = APIRouter(prefix="/api/emulator", tags=["emulator"])

SHOT_RE = re.compile(r"^emu_[a-z_]+_[0-9a-f]{8}\.png$")


class DeviceIn(BaseModel):
    addr: str = Field(min_length=3, max_length=64)


class TestUploadIn(DeviceIn):
    video_id: int
    go_to_post: bool = False


@router.post("/device")
def device(body: DeviceIn):
    try:
        return emulator.device_info(body.addr)
    except emulator.EmulatorError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/test-upload")
def test_upload(body: TestUploadIn, db: Session = Depends(get_db)):
    video = db.get(Video, body.video_id)
    if video is None:
        raise HTTPException(404, "Видео не найдено")
    path = os.path.join(settings.videos_dir, video.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл видео не найден на диске")
    try:
        return emulator.test_upload(body.addr, path, go_to_post=body.go_to_post)
    except emulator.EmulatorError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/screenshot/{name}")
def screenshot(name: str):
    if not SHOT_RE.match(name):
        raise HTTPException(404, "Снимок не найден")
    path = os.path.join(settings.output_dir, name)
    if not os.path.exists(path):
        raise HTTPException(404, "Снимок не найден")
    return FileResponse(path, media_type="image/png")
