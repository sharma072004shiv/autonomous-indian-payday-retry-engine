"""
app/db/connection.py
────────────────────
SQLite connection management with WAL mode.

Design decisions:
  - A single aiosqlite connection is held per process lifetime, opened at
    startup and closed at shutdown via app/main.py lifespan hooks.
  - WAL (Write-Ahead Logging) mode is set once at init; it persists in the
    database file so subsequent opens inherit it automatically.
  - PRAGMA foreign_keys = ON is set on every new connection because SQLite
    resets it per-connection.
  - Row factory is set to aiosqlite.Row so callers can access columns by name.
  - Tests pass an explicit db_path (usually ":memory:") via init_database();
    production uses the path from Settings.
  - get_connection() raises RuntimeError if called before init_database().

Thread/task safety:
  aiosqlite serialises all operations through a single background thread, so
  concurrent asyncio tasks sharing one connection are safe.  For the concurrency
  tests we rely on SQLite's built-in serialisation + the UNIQUE constraint on
  processed_events.event_id to prevent duplicate event processing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import aiosqlite

from app.db.schema import ALL_DDL

logger = logging.getLogger(__name__)

# Module-level singleton connection.  None until init_database() is called.
_connection: Optional[aiosqlite.Connection] = None


async def init_database(db_path: Optional[str] = None) -> None:
    """
    Open the SQLite database, enable WAL mode and foreign keys, then run
    all DDL statements to create tables and indexes if they don't exist.

    Parameters
    ----------
    db_path:
        Override the database file path.  Defaults to the value in Settings.
        Pass ":memory:" in tests for a fast, isolated, in-memory database.

    This function is idempotent: calling it a second time with the same path
    is a no-op (the existing connection is reused).
    """
    global _connection

    if _connection is not None:
        logger.debug("init_database called but connection already open — skipping")
        return

    # Resolve path
    if db_path is None:
        from app.config import get_settings
        db_path = get_settings().database_path

    # Ensure the data directory exists for file-backed databases
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening database at %s", os.path.abspath(db_path))
    else:
        logger.info("Opening in-memory SQLite database")

    conn = await aiosqlite.connect(db_path)

    # Row factory: access columns by name
    conn.row_factory = aiosqlite.Row

    # Enable WAL mode for better concurrent read performance and crash safety.
    # This is a persistent database setting; once set it survives close/reopen.
    await conn.execute("PRAGMA journal_mode = WAL;")

    # Enforce foreign-key constraints (must be set per connection in SQLite).
    await conn.execute("PRAGMA foreign_keys = ON;")

    # Reduce fsync calls slightly; still safe because WAL is enabled.
    await conn.execute("PRAGMA synchronous = NORMAL;")

    # Run all CREATE TABLE / CREATE INDEX statements
    for ddl in ALL_DDL:
        await conn.execute(ddl)

    await conn.commit()

    _connection = conn
    logger.info("Database initialised (schema version 2, WAL mode)")


async def get_connection() -> aiosqlite.Connection:
    """
    Return the open database connection.

    Raises
    ------
    RuntimeError
        If called before init_database() has completed successfully.
    """
    if _connection is None:
        raise RuntimeError(
            "Database connection is not open. "
            "Call init_database() before using get_connection()."
        )
    return _connection


async def close_database() -> None:
    """
    Close the global database connection.

    Called from app/main.py lifespan shutdown hook.
    Safe to call even if the connection was never opened.
    """
    global _connection

    if _connection is None:
        logger.debug("close_database called but no connection is open — skipping")
        return

    await _connection.close()
    _connection = None
    logger.info("Database connection closed")


async def reset_database() -> None:
    """
    Close and clear the connection, then drop and recreate all tables.

    ONLY for use in tests.  Never call this in production code.
    """
    global _connection

    if _connection is not None:
        await _connection.close()
        _connection = None
