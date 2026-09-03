"""Группы аккаунтов — когорты для проверки гипотез постинга.

Справочник намеренно плоский: имя, цвет бейджа и всё. На рендер и постинг группа
не влияет, она нужна только чтобы отобрать аккаунты в форме поста и разложить
статистику. Раскрытием «группа → список аккаунтов» занимается панель, поэтому
posting.py про группы ничего не знает и по-прежнему получает account_ids.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, AccountGroup
from ..schemas import AccountGroupCreate, AccountGroupOut, AccountGroupUpdate

router = APIRouter(prefix="/api/account-groups", tags=["account-groups"])


def _counts(db: Session) -> dict[int, int]:
    """Сколько аккаунтов в каждой группе — одним запросом, без N+1."""
    rows = (
        db.query(Account.group_id, func.count(Account.id))
        .filter(Account.group_id.isnot(None))
        .group_by(Account.group_id)
        .all()
    )
    return {gid: n for gid, n in rows}


def _out(row: AccountGroup, counts: dict[int, int]) -> AccountGroupOut:
    return AccountGroupOut(
        id=row.id, name=row.name, color=row.color,
        accounts_count=counts.get(row.id, 0), created_at=row.created_at,
    )


def _ensure_name_free(db: Session, name: str, exclude_id: int | None = None) -> None:
    """Имена групп уникальны без учёта регистра: «Прогретые» и «прогретые» — одна гипотеза.

    Сравниваем в Python, а не через lower() в SQL: у SQLite встроенный lower()
    работает только с латиницей, и кириллические дубли он бы пропустил (UNIQUE
    на колонке по той же причине тоже не спасает).
    """
    needle = name.casefold()
    for row in db.query(AccountGroup.id, AccountGroup.name).all():
        if row.id != exclude_id and row.name.casefold() == needle:
            raise HTTPException(409, f"Группа «{name}» уже есть")


@router.get("", response_model=list[AccountGroupOut])
def list_groups(db: Session = Depends(get_db)):
    counts = _counts(db)
    rows = db.query(AccountGroup).order_by(AccountGroup.name).all()
    return [_out(r, counts) for r in rows]


@router.post("", response_model=AccountGroupOut)
def create_group(payload: AccountGroupCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "У группы должно быть имя")
    _ensure_name_free(db, name)
    row = AccountGroup(name=name, color=payload.color or None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.patch("/{group_id}", response_model=AccountGroupOut)
def update_group(group_id: int, payload: AccountGroupUpdate, db: Session = Depends(get_db)):
    row = db.get(AccountGroup, group_id)
    if row is None:
        raise HTTPException(404, "Группа не найдена")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(400, "У группы должно быть имя")
        _ensure_name_free(db, name, exclude_id=row.id)
        row.name = name
    if payload.color is not None:
        row.color = payload.color or None
    db.commit()
    db.refresh(row)
    return _out(row, _counts(db))


@router.delete("/{group_id}")
def delete_group(group_id: int, db: Session = Depends(get_db)):
    """Удаляет группу, аккаунты остаются — у них просто пропадает принадлежность.

    Отвязываем явно: внешний ключ на accounts.group_id в SQLite не создаётся
    (колонка добавлена через ALTER TABLE), и без этого у аккаунтов остался бы
    висячий id, а селектор в панели показал бы пустое значение.
    """
    row = db.get(AccountGroup, group_id)
    if row is None:
        raise HTTPException(404, "Группа не найдена")
    detached = (
        db.query(Account).filter(Account.group_id == group_id)
        .update({Account.group_id: None}, synchronize_session=False)
    )
    db.delete(row)
    db.commit()
    return {"ok": True, "detached": detached}
