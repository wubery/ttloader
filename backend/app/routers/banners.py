from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Banner, BannerType
from ..schemas import BannerOut, BannerUpdate

router = APIRouter(prefix="/api/banners", tags=["banners"])

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


@router.get("", response_model=list[BannerOut])
def list_banners(db: Session = Depends(get_db)):
    return db.query(Banner).order_by(Banner.id.desc()).all()


@router.post("", response_model=BannerOut)
async def upload_banner(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext in IMAGE_EXT:
        btype = BannerType.image
    elif ext in VIDEO_EXT:
        btype = BannerType.video
    else:
        raise HTTPException(400, f"Неподдерживаемый формат баннера: {ext}")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.banners_dir, fname)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    banner = Banner(
        name=name or os.path.splitext(file.filename or fname)[0],
        type=btype,
        filename=fname,
    )
    db.add(banner)
    db.commit()
    db.refresh(banner)
    return banner


@router.patch("/{banner_id}", response_model=BannerOut)
def update_banner(banner_id: int, payload: BannerUpdate, db: Session = Depends(get_db)):
    banner = db.get(Banner, banner_id)
    if banner is None:
        raise HTTPException(404, "Баннер не найден")
    for field in ("name", "x", "y", "scale", "opacity", "motion", "motion_speed"):
        val = getattr(payload, field)
        if val is not None:
            setattr(banner, field, val)
    db.commit()
    db.refresh(banner)
    return banner


@router.get("/{banner_id}/file")
def get_banner_file(banner_id: int, db: Session = Depends(get_db)):
    banner = db.get(Banner, banner_id)
    if banner is None:
        raise HTTPException(404, "Баннер не найден")
    path = os.path.join(settings.banners_dir, banner.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл баннера отсутствует")
    return FileResponse(path)


@router.delete("/{banner_id}")
def delete_banner(banner_id: int, db: Session = Depends(get_db)):
    banner = db.get(Banner, banner_id)
    if banner is None:
        raise HTTPException(404, "Баннер не найден")
    path = os.path.join(settings.banners_dir, banner.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(banner)
    db.commit()
    return {"ok": True}
