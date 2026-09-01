"""Библиотека хуков — коротких заставок, которые клеятся в начало ролика.

Устроено как библиотека баннеров, но с probe после загрузки: длительность
заставки нужна конвейеру уникализации для расчёта обрезки и тишины.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Hook
from ..schemas import HookOut
from ..services import media

router = APIRouter(prefix="/api/hooks", tags=["hooks"])

ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


@router.get("", response_model=list[HookOut])
def list_hooks(db: Session = Depends(get_db)):
    return db.query(Hook).order_by(Hook.id.desc()).all()


@router.post("", response_model=HookOut)
async def upload_hook(
    file: UploadFile = File(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Неподдерживаемый формат: {ext}. Разрешены: {', '.join(sorted(ALLOWED_EXT))}")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.hooks_dir, fname)
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

    hook = Hook(
        name=name or os.path.splitext(file.filename or fname)[0],
        filename=fname, width=width, height=height, duration=duration,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    return hook


@router.get("/{hook_id}/file")
def get_hook_file(hook_id: int, db: Session = Depends(get_db)):
    hook = db.get(Hook, hook_id)
    if hook is None:
        raise HTTPException(404, "Хук не найден")
    path = os.path.join(settings.hooks_dir, hook.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл хука отсутствует")
    return FileResponse(path)


@router.delete("/{hook_id}")
def delete_hook(hook_id: int, db: Session = Depends(get_db)):
    hook = db.get(Hook, hook_id)
    if hook is None:
        raise HTTPException(404, "Хук не найден")
    path = os.path.join(settings.hooks_dir, hook.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(hook)
    db.commit()
    return {"ok": True}
