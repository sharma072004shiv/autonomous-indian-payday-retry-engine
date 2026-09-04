"""
tests/unit/test_db_schema.py
─────────────────────────────
Tests for database initialisation, WAL mode, and schema correctness.
"""

from __future__ import annotations

import pytest

from app.db.connection import (
    close_database,
    get_connection,
    init_database,
    reset_database,
)
from app.db.schema import EXPECTED_TABLES, SCHEMA_VERSION


# ── Schema version ────────────────────────────────────────────────────────────

def test_schema_version_is_correct() -> None:
    assert SCHEMA_VERSION == 2


def test_expected_tables_set() -> None:
    assert EXPECTED_TABLES == {
        "transactions",
        "processed_events",
        "retry_attempts",
        "audit_log",
    }


# ── Connection lifecycle ──────────────────────────────────────────────────────

async def test_get_connection_raises_before_init() -> None:
    """get_connection() must raise RuntimeError if init_database() was not called."""
    await reset_database()  # ensure clean state
    with pytest.raises(RuntimeError, match="not open"):
        await get_connection()


async def test_init_creates_connection(db) -> None:
    """After init_database(), get_connection() must succeed."""
    conn = await get_connection()
    assert conn is not None


async def test_init_is_idempotent(db) -> None:
    """Calling init_database() twice must not raise or create a second connection."""
    conn_first = await get_connection()
    await init_database(":memory:")  # second call — should be a no-op
    conn_second = await get_connection()
    assert conn_first is conn_second


async def test_close_then_get_raises(db) -> None:
    """After close_database(), get_connection() must raise RuntimeError."""
    await close_database()
    with pytest.raises(RuntimeError, match="not open"):
        await get_connection()
    # Restore for teardown
    await init_database(":memory:")


# ── WAL mode ─────────────────────────────────────────────────────────────────

async def test_wal_mode_pragma_executed(db) -> None:
    """
    init_database() sets PRAGMA journal_mode = WAL.

    SQLite `:memory:` databases silently ignore this pragma and report
    'memory' — this is documented SQLite behaviour, not a code defect.
    File-backed databases will report 'wal'.

    This test verifies the PRAGMA round-trips without error and returns a
    recognised journal mode string.
    """
    conn = await get_connection()
    async with conn.execute("PRAGMA journal_mode;") as cur:
        row = await cur.fetchone()
    mode = row[0].lower()
    # In-memory DBs return 'memory'; file DBs return 'wal' after our init.
    assert mode in {"wal", "memory"}, f"Unexpected journal_mode: {mode}"


async def test_wal_mode_enabled_file_db(tmp_path) -> None:
    """
    For a real file-backed database, journal_mode must be 'wal'.

    Uses a temporary file so this test is still isolated and self-cleaning.
    """
    from app.db.connection import close_database, init_database, reset_database

    db_file = str(tmp_path / "test_wal.db")
    await reset_database()           # ensure clean singleton
    try:
        await init_database(db_file)
        conn = await get_connection()
        async with conn.execute("PRAGMA journal_mode;") as cur:
            row = await cur.fetchone()
        assert row[0].lower() == "wal"
    finally:
        await close_database()
        await reset_database()


# ── Foreign key enforcement ───────────────────────────────────────────────────

async def test_foreign_keys_enabled(db) -> None:
    """PRAGMA foreign_keys must return 1 (ON)."""
    conn = await get_connection()
    async with conn.execute("PRAGMA foreign_keys;") as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ── Table existence ───────────────────────────────────────────────────────────

async def test_all_tables_created(db) -> None:
    """Every table in EXPECTED_TABLES must exist after init."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    ) as cur:
        rows = await cur.fetchall()
    actual = {row[0] for row in rows}
    assert EXPECTED_TABLES.issubset(actual), (
        f"Missing tables: {EXPECTED_TABLES - actual}"
    )


async def test_transactions_table_columns(db) -> None:
    """transactions table must have the expected columns."""
    conn = await get_connection()
    async with conn.execute("PRAGMA table_info(transactions);") as cur:
        rows = await cur.fetchall()
    columns = {row[1] for row in rows}
    required = {
        "transaction_id", "failure_code", "amount_paise", "customer_id",
        "mandate_id", "occurred_at", "created_at", "updated_at",
        "status", "failure_category", "llm_confidence",
        "retry_count", "next_retry_at", "last_retry_at",
    }
    assert required.issubset(columns), f"Missing columns: {required - columns}"


async def test_processed_events_table_columns(db) -> None:
    conn = await get_connection()
    async with conn.execute("PRAGMA table_info(processed_events);") as cur:
        rows = await cur.fetchall()
    columns = {row[1] for row in rows}
    assert {"event_id", "transaction_id", "received_at"}.issubset(columns)


async def test_retry_attempts_table_columns(db) -> None:
    conn = await get_connection()
    async with conn.execute("PRAGMA table_info(retry_attempts);") as cur:
        rows = await cur.fetchall()
    columns = {row[1] for row in rows}
    required = {
        "attempt_id", "transaction_id", "event_id", "attempt_number",
        "scheduled_at", "executed_at", "outcome",
        "failure_code_at_retry", "diagnosis", "created_at",
    }
    assert required.issubset(columns), f"Missing columns: {required - columns}"


async def test_audit_log_table_columns(db) -> None:
    conn = await get_connection()
    async with conn.execute("PRAGMA table_info(audit_log);") as cur:
        rows = await cur.fetchall()
    columns = {row[1] for row in rows}
    required = {
        "audit_id", "transaction_id", "event_id",
        "decision", "failure_category", "policy_rule_applied", "reason",
        "llm_confidence", "llm_rationale",
        "retry_scheduled_at", "retry_attempt_number", "decided_at",
    }
    assert required.issubset(columns), f"Missing columns: {required - columns}"


# ── Indexes ───────────────────────────────────────────────────────────────────

async def test_indexes_created(db) -> None:
    """Expected indexes must exist."""
    conn = await get_connection()
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index';"
    ) as cur:
        rows = await cur.fetchall()
    index_names = {row[0] for row in rows}
    expected_indexes = {
        "idx_transactions_status",
        "idx_transactions_next_retry",
        "idx_retry_attempts_transaction",
        "idx_audit_log_transaction",
    }
    assert expected_indexes.issubset(index_names), (
        f"Missing indexes: {expected_indexes - index_names}"
    )
