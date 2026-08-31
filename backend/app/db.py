from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# timeout: при нескольких параллельных задачах постинга лог пишется часто, и без
# ожидания SQLite сразу отдаёт «database is locked».
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

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


def _sql_literal(value: object) -> str:
    """Значение по умолчанию в виде SQL-литерала."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    try:  # числовые строки не кавычим, иначе в SQLite поедут типы
        float(s)
        return s
    except ValueError:
        return "'" + s.replace("'", "''") + "'"


def _default_sql(col) -> str | None:
    """SQL-литерал значения по умолчанию колонки (server_default или Python-default)."""
    sd = col.server_default
    if sd is not None:
        arg = getattr(sd, "arg", None)
        # TextClause (text("...")) — берём как есть, строку/число — как литерал
        clause = getattr(arg, "text", None)
        if clause is not None:
            return clause
        if arg is not None:
            return _sql_literal(arg)
    d = col.default
    if d is not None and getattr(d, "is_scalar", False):
        return _sql_literal(d.arg)
    return None


def _auto_migrate() -> None:
    """Лёгкая авто-миграция (dev-режим без alembic): добавить недостающие колонки
    в уже существующие таблицы через ALTER TABLE ADD COLUMN. Новые таблицы создаёт
    create_all. Новые колонки должны быть nullable или иметь default/server_default."""
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            dsql = _default_sql(col)
            if col.name not in existing:
                coltype = col.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                if dsql is not None:
                    ddl += f" DEFAULT {dsql}"
                with engine.begin() as conn:
                    conn.execute(text(ddl))
            # Строки, созданные до появления колонки, могли остаться с NULL (раньше
            # DEFAULT в ALTER не подставлялся) — для NOT NULL-колонок это ломает
            # ответы API «Input should be a valid string». Дозаполняем.
            if not col.nullable and dsql is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text(f'UPDATE "{table.name}" SET "{col.name}" = {dsql} WHERE "{col.name}" IS NULL')
                    )


def init_db() -> None:
    """Создать каталоги данных и таблицы (dev-режим без alembic)."""
    from . import models  # noqa: F401

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _auto_migrate()
