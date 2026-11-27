from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

IS_SQLITE = settings.database_url.startswith("sqlite")
# timeout: how long a writer waits for another writer before giving up (seconds).
_connect_args = {"check_same_thread": False, "timeout": 30} if IS_SQLITE else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        # WAL lets the interface keep reading while a background scan writes, which is what
        # previously caused "database is locked" errors. busy_timeout makes writers wait their turn.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    add_missing_columns()


def add_missing_columns() -> list[str]:
    """New nullable columns on tables that already exist (create_all only makes new tables). Runs before anything
    reads the tables, so an update never meets a 'no such column' error."""
    from sqlalchemy import inspect, text
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable or col.primary_key:
                    continue
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'))
                added.append(f"{table.name}.{col.name}")
    return added
