import os
from pathlib import Path

from sqlalchemy import event
from sqlmodel import create_engine

DB_URL = os.getenv("DB_URL", "sqlite:///./curiarium.db")
STORAGE = Path(os.getenv("FILE_STORAGE", "./storage"))
STORAGE.mkdir(parents=True, exist_ok=True)
THUMBS = STORAGE / "thumbs"
THUMBS.mkdir(parents=True, exist_ok=True)

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})


if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """Make concurrent writers wait instead of failing with 'database is locked'.

        WAL lets readers proceed while a writer commits; busy_timeout makes the
        background backfill threads and request handlers queue instead of
        raising OperationalError when they collide. foreign_keys is per
        connection, so it must live here: this API engine is the only writer by
        design, and an external tool that connects without this listener gets no
        enforcement at all. It cannot go in a startup PRAGMA statement because
        SQLite silently ignores `PRAGMA foreign_keys` inside a transaction.
        """
        cursor = dbapi_connection.cursor()
        try:
            if ":memory:" not in DB_URL:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
