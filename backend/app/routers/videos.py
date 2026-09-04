from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AssetFolder, Job, Video
from ..schemas import ChunkFinish, FolderAssign, VideoOut
from ..services import media, storage

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
    fname = await storage.save_upload(file, settings.videos_dir, ext)
    return _register(db, fname, file.filename or fname)


def _register(db: Session, fname: str, original_name: str) -> Video:
    """Заводит ролик в библиотеке по уже сохранённому файлу."""
    path = os.path.join(settings.videos_dir, fname)
    width = height = None
    duration = None
    try:
        info = media.probe(path)
        width, height, duration = info.width, info.height, info.duration
    except media.MediaError:
        pass  # ffmpeg может быть не установлен — размеры проставятся позже

    video = Video(
        title=os.path.splitext(original_name or fname)[0],
        filename=fname,
        width=width, height=height, duration=duration,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.post("/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    file: UploadFile = File(...),
):
    """Принимает один кусок длинного ролика (см. services/storage.py).

    Куски идут подряд: index=0 создаёт файл заново, остальные дописываются.
    Так заливка проходит через прокси с лимитом на размер тела и переживает
    обрыв — повторяется один кусок, а не весь ролик.
    """
    settings.ensure_dirs()
    size = await storage.append_chunk(file, settings.videos_dir, upload_id, first=index == 0)
    return {"ok": True, "received": size}


@router.post("/chunk/finish", response_model=VideoOut)
def finish_chunk_upload(payload: ChunkFinish, db: Session = Depends(get_db)):
    ext = os.path.splitext(payload.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        storage.abort_chunks(settings.videos_dir, payload.upload_id)
        raise HTTPException(400, f"Неподдерживаемый формат: {ext}. Разрешены: {', '.join(sorted(ALLOWED_EXT))}")
    fname = storage.finish_chunks(settings.videos_dir, payload.upload_id, ext)
    return _register(db, fname, payload.filename)


@router.delete("/chunk/{upload_id}")
def abort_chunk_upload(upload_id: str):
    """Отмена заливки: недособранный файл не должен занимать диск."""
    storage.abort_chunks(settings.videos_dir, upload_id)
    return {"ok": True}


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
def delete_video(video_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Удаляет видео. С задачами — только по force.

    jobs.video_id объявлен NOT NULL, поэтому обычное удаление ролика, на который
    ссылается хоть одна задача, падало на уровне БД пятисоткой («не могу удалить
    старые видео»). Теперь панель честно говорит, сколько задач мешает, и удаляет
    их вместе с роликом, если пользователь подтвердил: задача без исходника всё
    равно нерабочая. Вместе с задачами убираем и их отрендеренные файлы.
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Видео не найдено")

    jobs = db.query(Job).filter(Job.video_id == video_id).all()
    if jobs and not force:
        raise HTTPException(
            409,
            f"На это видео завязано задач: {len(jobs)}. "
            f"Удаление сотрёт их вместе с историей публикаций.",
        )
    for job in jobs:
        if job.output_filename:
            rendered = os.path.join(settings.output_dir, job.output_filename)
            if os.path.exists(rendered):
                os.remove(rendered)
        db.delete(job)

    path = os.path.join(settings.videos_dir, video.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(video)
    db.commit()
    return {"ok": True, "deleted_jobs": len(jobs)}
