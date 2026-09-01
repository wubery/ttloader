"""Библиотека рекламных роликов — вставляются внутрь части видео.

Устроено как библиотека хуков: probe после загрузки нужен, чтобы знать
длительность вставки и подставить тишину, если у ролика нет звука.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AdClip
from ..schemas import AdClipOut
from ..services import media

router = APIRouter(prefix="/api/ads", tags=["ads"])

ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


@router.get("", response_model=list[AdClipOut])
def list_ads(db: Session = Depends(get_db)):
    return db.query(AdClip).order_by(AdClip.id.desc()).all()


@router.post("", response_model=AdClipOut)
async def upload_ad(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Неподдерживаемый формат: {ext}. Разрешены: {', '.join(sorted(ALLOWED_EXT))}")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.ads_dir, fname)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    width = height = None
    duration = None
    try:
        info = media.probe(path)
        width, height, duration = info.width, info.height, info.duration
    except media.MediaError:
        pass  # ffmpeg может быть недоступен — размеры проставятся позже

    ad = AdClip(
        name=name or os.path.splitext(file.filename or fname)[0],
        filename=fname, width=width, height=height, duration=duration,
    )
    db.add(ad)
    db.commit()
    db.refresh(ad)
    return ad


@router.get("/{ad_id}/file")
def get_ad_file(ad_id: int, db: Session = Depends(get_db)):
    ad = db.get(AdClip, ad_id)
    if hook is None:
        raise HTTPException(404, "Рекламный ролик не найден")
    path = os.path.join(settings.ads_dir, ad.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл рекламы отсутствует")
    return FileResponse(path)


@router.delete("/{ad_id}")
def delete_ad(ad_id: int, db: Session = Depends(get_db)):
    ad = db.get(AdClip, ad_id)
    if hook is None:
        raise HTTPException(404, "Рекламный ролик не найден")
    path = os.path.join(settings.ads_dir, ad.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(ad)
    db.commit()
    return {"ok": True}
