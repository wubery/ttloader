"""Библиотека фонов: картинка или видео под рамку вокруг вписанного ролика."""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Background
from ..schemas import BackgroundOut

router = APIRouter(prefix="/api/backgrounds", tags=["backgrounds"])

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


@router.get("", response_model=list[BackgroundOut])
def list_backgrounds(db: Session = Depends(get_db)):
    return db.query(Background).order_by(Background.id.desc()).all()


@router.post("", response_model=BackgroundOut)
async def upload_background(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext in IMAGE_EXT:
        is_video = False
    elif ext in VIDEO_EXT:
        is_video = True
    else:
        raise HTTPException(400, f"Неподдерживаемый формат фона: {ext}")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.backgrounds_dir, fname)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    item = Background(
        name=name or os.path.splitext(file.filename or fname)[0],
        filename=fname, is_video=is_video,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{bg_id}/file")
def get_background_file(bg_id: int, db: Session = Depends(get_db)):
    item = db.get(Background, bg_id)
    if item is None:
        raise HTTPException(404, "Фон не найден")
    path = os.path.join(settings.backgrounds_dir, item.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл фона отсутствует")
    return FileResponse(path)


@router.delete("/{bg_id}")
def delete_background(bg_id: int, db: Session = Depends(get_db)):
    item = db.get(Background, bg_id)
    if item is None:
        raise HTTPException(404, "Фон не найден")
    path = os.path.join(settings.backgrounds_dir, item.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(item)
    db.commit()
    return {"ok": True}
