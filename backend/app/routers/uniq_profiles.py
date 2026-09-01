"""Профили уникализации: наборы диапазонов + предпросмотр на коротком отрывке."""
from __future__ import annotations

import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import UniqProfile, Video
from ..schemas import UniqProfileCreate, UniqProfileOut, UniqProfileUpdate
from ..services import media, uniqueizer

router = APIRouter(prefix="/api/uniq-profiles", tags=["uniq-profiles"])

# На предпросмотр берём короткий отрывок: полный рендер 1080×1920 идёт минутами.
PREVIEW_SECONDS = 3


def _out(row: UniqProfile) -> UniqProfileOut:
    """Параметры отдаём разобранным объектом и всегда дополненными до полного набора."""
    try:
        raw = json.loads(row.params) if row.params else {}
    except (TypeError, ValueError):
        raw = {}
    return UniqProfileOut(
        id=row.id, name=row.name, params=uniqueizer.merge_params(raw),
        is_default=row.is_default, created_at=row.created_at,
    )


def _clear_default(db: Session, keep_id: int | None = None) -> None:
    for row in db.query(UniqProfile).filter(UniqProfile.is_default.is_(True)).all():
        if row.id != keep_id:
            row.is_default = False


@router.get("", response_model=list[UniqProfileOut])
def list_profiles(db: Session = Depends(get_db)):
    return [_out(r) for r in db.query(UniqProfile).order_by(UniqProfile.id.desc()).all()]


@router.get("/defaults")
def default_params():
    """Пустой шаблон профиля — им фронт заполняет форму создания."""
    return uniqueizer.DEFAULT_PARAMS


@router.post("", response_model=UniqProfileOut)
def create_profile(payload: UniqProfileCreate, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "У профиля должно быть имя")
    row = UniqProfile(
        name=payload.name.strip(),
        params=json.dumps(payload.params or uniqueizer.DEFAULT_PARAMS, ensure_ascii=False),
        is_default=payload.is_default,
    )
    if payload.is_default:
        _clear_default(db)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch("/{profile_id}", response_model=UniqProfileOut)
def update_profile(profile_id: int, payload: UniqProfileUpdate, db: Session = Depends(get_db)):
    row = db.get(UniqProfile, profile_id)
    if row is None:
        raise HTTPException(404, "Профиль не найден")
    if payload.name is not None:
        row.name = payload.name.strip() or row.name
    if payload.params is not None:
        row.params = json.dumps(payload.params, ensure_ascii=False)
    if payload.is_default is not None:
        row.is_default = payload.is_default
        if payload.is_default:
            _clear_default(db, keep_id=row.id)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    row = db.get(UniqProfile, profile_id)
    if row is None:
        raise HTTPException(404, "Профиль не найден")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{profile_id}/preview")
def preview_profile(profile_id: int, video_id: int, db: Session = Depends(get_db)):
    """Рендерит несколько секунд с настройками профиля — чтобы не подбирать вслепую."""
    row = db.get(UniqProfile, profile_id)
    if row is None:
        raise HTTPException(404, "Профиль не найден")
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Видео не найдено")

    src = os.path.join(settings.videos_dir, video.filename)
    if not os.path.exists(src):
        raise HTTPException(404, "Файл видео отсутствует")

    settings.ensure_dirs()
    cut = os.path.join(settings.output_dir, f"preview_cut_{profile_id}.mp4")
    out = os.path.join(settings.output_dir, f"preview_{profile_id}_{int(time.time())}.mp4")
    try:
        # сначала короткий отрывок, потом уже конвейер — так предпросмотр занимает секунды
        media._run([
            settings.ffmpeg_bin, "-y", "-v", "error", "-t", str(PREVIEW_SECONDS),
            "-i", src, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", cut,
        ], timeout=300)
        params = json.loads(row.params) if row.params else {}
        uniqueizer.render(video_path=cut, output_path=out, params=params)
    except media.MediaError as e:
        raise HTTPException(500, f"Не удалось собрать предпросмотр: {e}") from e
    finally:
        if os.path.exists(cut):
            os.remove(cut)
    return FileResponse(out, media_type="video/mp4", filename=os.path.basename(out))
