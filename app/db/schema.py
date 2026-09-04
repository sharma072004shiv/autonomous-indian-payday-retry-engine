"""
app/db/schema.py
────────────────
SQLite DDL for the PayDay Retry Engine.

Four tables:
  1. transactions      — one row per failed payment transaction
  2. processed_events  — idempotency guard; one row per ingested webhook event_id
  3. retry_attempts    — one row per retry attempt (history)
  4. audit_log         — append-only decisions made by the policy engine

Design rules:
  - All datetimes are stored as ISO-8601 TEXT in UTC.
  - All amounts are stored as INTEGER paise (100 paise = ₹1).
  - Enum fields are stored as TEXT; CHECK constraints enforce valid values.
  - processed_events.event_id has a UNIQUE constraint for idempotency.
  - audit_log has no UPDATE or DELETE path by convention; the repository
    enforces this at the Python layer.
"""

from __future__ import annotations

SCHEMA_VERSION: int = 2

# ── Table 1: transactions ─────────────────────────────────────────────────────
CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      TEXT    PRIMARY KEY,
    failure_code        TEXT    NOT NULL,
    amount_paise        INTEGER NOT NULL CHECK (amount_paise >= 0),
    customer_id         TEXT    NOT NULL,
    mandate_id          TEXT,

    occurred_at         TEXT    NOT NULL,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL,

    status              TEXT    NOT NULL DEFAULT 'FAILED'
                                CHECK (status IN (
                                    'PENDING',
                                    'FAILED',
                                    'RETRY_SCHEDULED',
                                    'RETRY_IN_PROGRESS',
                                    'RECOVERED',
                                    'PERMANENTLY_FAILED'
                                )),

    failure_category    TEXT    CHECK (failure_category IN (
                                    'LIQUIDITY_TEMPORARY',
                                    'BANK_SURGE_TEMPORARY',
                                    'HARD_DECLINE'
                                )),
    llm_confidence      REAL    CHECK (llm_confidence IS NULL OR
                                       (llm_confidence >= 0.0 AND llm_confidence <= 1.0)),

    retry_count         INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0 AND retry_count <= 3),
    next_retry_at       TEXT,
    last_retry_at       TEXT
);
"""

CREATE_TRANSACTIONS_IDX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_transactions_status
    ON transactions (status);
"""

CREATE_TRANSACTIONS_IDX_NEXT_RETRY = """
CREATE INDEX IF NOT EXISTS idx_transactions_next_retry
    ON transactions (next_retry_at)
    WHERE next_retry_at IS NOT NULL;
"""

# ── Table 2: processed_events ─────────────────────────────────────────────────
# The UNIQUE constraint on event_id is the database-level idempotency guard.
# An INSERT OR IGNORE on this table is the safe atomic check-and-mark.
CREATE_PROCESSED_EVENTS = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id            TEXT    PRIMARY KEY,
    transaction_id      TEXT    NOT NULL,
    received_at         TEXT    NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id)
);
"""

# ── Table 3: retry_attempts ───────────────────────────────────────────────────
CREATE_RETRY_ATTEMPTS = """
CREATE TABLE IF NOT EXISTS retry_attempts (
    attempt_id          TEXT    PRIMARY KEY,
    transaction_id      TEXT    NOT NULL,
    event_id            TEXT    NOT NULL,
    attempt_number      INTEGER NOT NULL CHECK (attempt_number >= 1 AND attempt_number <= 3),

    scheduled_at        TEXT    NOT NULL,
    executed_at         TEXT,

    outcome             TEXT    CHECK (outcome IS NULL OR outcome IN (
                                    'SUCCESS',
                                    'FAILURE',
                                    'TIMEOUT'
                                )),
    failure_code_at_retry  TEXT,
    diagnosis           TEXT,

    created_at          TEXT    NOT NULL,

    FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id)
);
"""

CREATE_RETRY_ATTEMPTS_IDX_TXN = """
CREATE INDEX IF NOT EXISTS idx_retry_attempts_transaction
    ON retry_attempts (transaction_id);
"""

# ── Table 4: audit_log ────────────────────────────────────────────────────────
CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id                TEXT    PRIMARY KEY,
    transaction_id          TEXT    NOT NULL,
    event_id                TEXT    NOT NULL,

    decision                TEXT    NOT NULL
                                    CHECK (decision IN ('APPROVE', 'REJECT', 'DEFER')),
    failure_category        TEXT    NOT NULL
                                    CHECK (failure_category IN (
                                        'LIQUIDITY_TEMPORARY',
                                        'BANK_SURGE_TEMPORARY',
                                        'HARD_DECLINE'
                                    )),
    policy_rule_applied     TEXT    NOT NULL,
    reason                  TEXT    NOT NULL,

    llm_confidence          REAL    CHECK (llm_confidence IS NULL OR
                                           (llm_confidence >= 0.0 AND llm_confidence <= 1.0)),
    llm_rationale           TEXT,

    retry_scheduled_at      TEXT,
    retry_attempt_number    INTEGER NOT NULL DEFAULT 0 CHECK (retry_attempt_number >= 0),

    decided_at              TEXT    NOT NULL,

    FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id)
);
"""

CREATE_AUDIT_LOG_IDX_TXN = """
CREATE INDEX IF NOT EXISTS idx_audit_log_transaction
    ON audit_log (transaction_id, decided_at);
"""

# ── Ordered list executed by init_database() ─────────────────────────────────
ALL_DDL: list[str] = [
    CREATE_TRANSACTIONS,
    CREATE_TRANSACTIONS_IDX_STATUS,
    CREATE_TRANSACTIONS_IDX_NEXT_RETRY,
    CREATE_PROCESSED_EVENTS,
    CREATE_RETRY_ATTEMPTS,
    CREATE_RETRY_ATTEMPTS_IDX_TXN,
    CREATE_AUDIT_LOG,
    CREATE_AUDIT_LOG_IDX_TXN,
]

# Set of table names the schema creates (used in tests).
EXPECTED_TABLES: frozenset[str] = frozenset({
    "transactions",
    "processed_events",
    "retry_attempts",
    "audit_log",
})
