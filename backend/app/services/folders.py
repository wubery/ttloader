"""Доступность файлов библиотек группам аккаунтов.

Правило одно и то же для видео, хуков и фонов:

* файл без папки доступен всем — иначе после обновления вся имеющаяся библиотека
  разом стала бы недоступной;
* папка без групп тоже ничего не ограничивает: это просто полка, а не фильтр;
* как только на папку повешена хотя бы одна группа, её содержимое видно только
  этим группам.

Аккаунт без группы ничем не ограничен: сужать выбор не по чему.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AssetFolder

# kind папки → модель библиотеки
KINDS = ("video", "hook", "background")


def allowed_folder_ids(db: Session, kind: str, group_id: int | None) -> set[int] | None:
    """id папок, доступных группе. None — ограничивать нечем (аккаунт без группы)."""
    if group_id is None:
        return None
    rows = db.query(AssetFolder).filter(AssetFolder.kind == kind).all()
    return {f.id for f in rows if not f.groups or any(g.id == group_id for g in f.groups)}


def visible_filter(model, allowed: set[int] | None):
    """Условие SQLAlchemy «этот файл доступен группе» либо None, если фильтра нет."""
    if allowed is None:
        return None
    if not allowed:
        return model.folder_id.is_(None)          # доступных папок нет — только файлы без папки
    return (model.folder_id.is_(None)) | (model.folder_id.in_(allowed))


def visible_rows(db: Session, model, kind: str, group_id: int | None) -> list:
    """Файлы библиотеки, доступные группе."""
    q = db.query(model)
    cond = visible_filter(model, allowed_folder_ids(db, kind, group_id))
    if cond is not None:
        q = q.filter(cond)
    return q.all()
