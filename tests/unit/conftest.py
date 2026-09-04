"""
tests/unit/conftest.py
───────────────────────
Shared pytest fixtures for unit tests.

Each test function that needs a database gets a fresh in-memory SQLite
database via the `db` fixture.  The fixture:
  1. Calls init_database(":memory:") to open the connection and run DDL.
  2. Yields (test runs).
  3. Calls reset_database() to close and clear the module-level singleton,
     so the next test starts from a clean state.

All DB tests must use `async def` and will be collected by pytest-asyncio
(asyncio_mode = "auto" is set in pyproject.toml).
"""

from __future__ import annotations

import pytest

from app.db.connection import init_database, reset_database


@pytest.fixture
async def db():
    """
    Provide an initialised in-memory SQLite database for a single test.

    The connection singleton is cleared after each test so tests are isolated.
    """
    await init_database(":memory:")
    yield
    await reset_database()
