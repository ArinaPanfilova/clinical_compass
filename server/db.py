"""SQLite: соединение с надёжными настройками, схема, транзакция.

WAL позволяет читать параллельно с записью; synchronous=FULL — подтверждённая запись
переживает сбой процесса и питания (важно для критических самоотчётов и алертов).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


@contextmanager
def tx(conn: sqlite3.Connection):
    """Явная транзакция: всё или ничего. BEGIN IMMEDIATE сразу берёт блокировку записи."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def loads(s):
    return json.loads(s) if s else None
