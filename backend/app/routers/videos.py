from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AssetFolder, Video
from ..schemas import FolderAssign, VideoOut
from ..services import media

router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}


@router.get("", response_model=list[VideoOut])
def list_videos(db: Session = Depends(get_db)):
    return db.query(Video).order_by(Video.id.desc()).all()


@router.post("", response_model=VideoOut)
async def upload_video(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Неподдерживаемый формат: {ext}. Разрешены: {', '.join(sorted(ALLOWED_EXT))}")

    settings.ensure_dirs()
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.videos_dir, fname)
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    width = height = None
    duration = None
    try:
        info = media.probe(path)
        width, height, duration = info.width, info.height, info.duration
    except media.MediaError:
        pass  # ffmpeg может быть не установлен — размеры проставятся позже

    video = Video(
        title=os.path.splitext(file.filename or fname)[0],
        filename=fname,
        width=width, height=height, duration=duration,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.patch("/{video_id}/folder", response_model=VideoOut)
def set_folder(video_id: int, payload: FolderAssign, db: Session = Depends(get_db)):
    """Переносит файл в папку; folder_id=null — вынуть из папки (доступно всем)."""
    row = db.get(Video, video_id)
    if row is None:
        raise HTTPException(404, "Видео не найдено")
    if payload.folder_id is not None:
        folder = db.get(AssetFolder, payload.folder_id)
        if folder is None or folder.kind != "video":
            raise HTTPException(404, "Папка не найдена")
    row.folder_id = payload.folder_id
    db.commit()
    db.refresh(row)
    return row


@router.get("/{video_id}/file")
def get_video_file(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Видео не найдено")
    path = os.path.join(settings.videos_dir, video.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Файл видео отсутствует")
    return FileResponse(path)


@router.delete("/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Видео не найдено")
    path = os.path.join(settings.videos_dir, video.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(video)
    db.commit()
    return {"ok": True}
