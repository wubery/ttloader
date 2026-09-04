"""Папки библиотек: раскладка видео, хуков и фонов + привязка папки к группам.

Папки у каждой библиотеки свои — различаются полем kind, имена не пересекаются
между библиотеками. Что папка даёт группам, описано в services/folders.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AccountGroup, AssetFolder, Background, Hook, Video
from ..schemas import AssetFolderCreate, AssetFolderOut, AssetFolderUpdate
from ..services.folders import KINDS

router = APIRouter(prefix="/api/asset-folders", tags=["asset-folders"])

# kind → модель библиотеки, которую эта папка раскладывает
MODELS = {"video": Video, "hook": Hook, "background": Background}


def _check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(400, f"Неизвестный вид папки: {kind}")
    return kind


def _counts(db: Session, kind: str) -> dict[int, int]:
    from sqlalchemy import func

    model = MODELS[kind]
    rows = (
        db.query(model.folder_id, func.count(model.id))
        .filter(model.folder_id.isnot(None))
        .group_by(model.folder_id)
        .all()
    )
    return {fid: n for fid, n in rows}


def _out(row: AssetFolder, counts: dict[int, int]) -> AssetFolderOut:
    return AssetFolderOut(
        id=row.id, kind=row.kind, name=row.name,
        group_ids=[g.id for g in row.groups],
        items_count=counts.get(row.id, 0), created_at=row.created_at,
    )


def _ensure_name_free(db: Session, kind: str, name: str, exclude_id: int | None = None) -> None:
    """Имя уникально внутри своей библиотеки, без учёта регистра.

    Сравниваем в Python: встроенный lower() у SQLite знает только латиницу.
    """
    needle = name.casefold()
    for row in db.query(AssetFolder).filter(AssetFolder.kind == kind).all():
        if row.id != exclude_id and row.name.casefold() == needle:
            raise HTTPException(409, f"Папка «{name}» в этой библиотеке уже есть")


def _apply_groups(db: Session, row: AssetFolder, group_ids: list[int]) -> None:
    ids = list(dict.fromkeys(group_ids))
    groups = db.query(AccountGroup).filter(AccountGroup.id.in_(ids)).all() if ids else []
    if len(groups) != len(ids):
        raise HTTPException(404, "Одна из групп не найдена")
    row.groups = groups


@router.get("", response_model=list[AssetFolderOut])
def list_folders(kind: str | None = Query(default=None), db: Session = Depends(get_db)):
    q = db.query(AssetFolder)
    if kind is not None:
        q = q.filter(AssetFolder.kind == _check_kind(kind))
    rows = q.order_by(AssetFolder.kind, AssetFolder.name).all()
    counts = {k: _counts(db, k) for k in {r.kind for r in rows}}
    return [_out(r, counts.get(r.kind, {})) for r in rows]


@router.post("", response_model=AssetFolderOut)
def create_folder(payload: AssetFolderCreate, db: Session = Depends(get_db)):
    kind = _check_kind(payload.kind)
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "У папки должно быть имя")
    _ensure_name_free(db, kind, name)
    row = AssetFolder(kind=kind, name=name)
    _apply_groups(db, row, payload.group_ids)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, kind))


@router.patch("/{folder_id}", response_model=AssetFolderOut)
def update_folder(folder_id: int, payload: AssetFolderUpdate, db: Session = Depends(get_db)):
    row = db.get(AssetFolder, folder_id)
    if row is None:
        raise HTTPException(404, "Папка не найдена")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, "У папки должно быть имя")
        _ensure_name_free(db, row.kind, name, exclude_id=row.id)
        row.name = name
    if payload.group_ids is not None:
        _apply_groups(db, row, payload.group_ids)
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db, row.kind))


@router.delete("/{folder_id}")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    """Удаляет папку; файлы остаются и становятся доступны всем группам.

    Отвязываем явно: внешнего ключа на folder_id в SQLite нет (колонки добавлены
    через ALTER TABLE), иначе у файлов остался бы висячий id.
    """
    row = db.get(AssetFolder, folder_id)
    if row is None:
        raise HTTPException(404, "Папка не найдена")
    model = MODELS[row.kind]
    detached = (
        db.query(model).filter(model.folder_id == folder_id)
        .update({model.folder_id: None}, synchronize_session=False)
    )
    row.groups = []
    db.delete(row)
    db.commit()
    return {"ok": True, "detached": detached}
