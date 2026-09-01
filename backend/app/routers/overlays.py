"""Библиотека полнокадровых PNG-оверлеев (текстуры, рамки, лёгкие засветки).

Отдельно от баннеров: баннер — логотип в углу со своей позицией и движением,
оверлей — картинка на весь кадр, часть конвейера уникализации.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import OverlayAsset
from ..schemas import OverlayAssetOut

router = APIRouter(prefix="/api/overlays", tags=["overlays"])

ALLOWED_EXT = {".png", ".webp"}   # нужен альфа-канал, поэтому без jpg


@router.get("", response_model=list[OverlayAssetOut])
def list_overlays(db: Session = Depends(get_db)):
    return db.query(OverlayAsset).order_by(OverlayAsset.id.desc()).all()


@router.post("", response_model=OverlayAssetOut)
async def upload_overlay(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Нужен PNG или WebP с прозрачностью — иначе оверлей закроет кадр.")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.overlays_dir, fname)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    item = OverlayAsset(name=name or os.path.splitext(file.filename or fname)[0], filename=fname)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{overlay_id}/file")
def get_overlay_file(overlay_id: int, db: Session = Depends(get_db)):
    item = db.get(OverlayAsset, overlay_id)
    if item is None:
        raise HTTPException(404, "Оверлей не найден")
    path = os.path.join(settings.overlays_dir, item.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл оверлея отсутствует")
    return FileResponse(path)


@router.delete("/{overlay_id}")
def delete_overlay(overlay_id: int, db: Session = Depends(get_db)):
    item = db.get(OverlayAsset, overlay_id)
    if item is None:
        raise HTTPException(404, "Оверлей не найден")
    path = os.path.join(settings.overlays_dir, item.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(item)
    db.commit()
    return {"ok": True}
