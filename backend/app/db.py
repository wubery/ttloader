from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _auto_migrate() -> None:
    """Лёгкая авто-миграция (dev-режим без alembic): добавить недостающие колонки
    в уже существующие таблицы через ALTER TABLE ADD COLUMN. Новые таблицы создаёт
    create_all. Новые колонки должны быть nullable или иметь server_default."""
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
            if col.server_default is not None:
                try:
                    ddl += f" DEFAULT {col.server_default.arg.text}"
                except Exception:  # noqa: BLE001
                    pass
            with engine.begin() as conn:
                conn.execute(text(ddl))


def init_db() -> None:
    """Создать каталоги данных и таблицы (dev-режим без alembic)."""
    from . import models  # noqa: F401

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _auto_migrate()
