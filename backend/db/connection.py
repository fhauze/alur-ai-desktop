"""
backend/db/connection.py
------------------------
Database connection pool for the ServiceIQ backend.

Credentials are read exclusively from environment variables. No credential
is ever hard-coded in this module or anywhere in the application.

Required environment variables
───────────────────────────────
  DB_HOST      PostgreSQL host          (default: localhost)
  DB_PORT      PostgreSQL port          (default: 5432)
  DB_NAME      Database name            (required)
  DB_USER      Database user            (required)
  DB_PASSWORD  Database password        (required)

Optional
────────
  DB_MIN_CONNECTIONS  Pool minimum size  (default: 2)
  DB_MAX_CONNECTIONS  Pool maximum size  (default: 10)
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import asyncpg
from asyncpg import Pool


# ---------------------------------------------------------------------------
# Module-level pool instance (None until initialised via init_pool())
# ---------------------------------------------------------------------------
_pool: Pool | None = None


def _dsn() -> str:
    """Build the PostgreSQL DSN from environment variables.

    Raises:
        EnvironmentError: if any required variable is missing.
    """
    missing = [v for v in ("DB_NAME", "DB_USER") if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required database environment variables: {', '.join(missing)}"
        )

    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    password = os.environ.get("DB_PASSWORD", "")

    # asyncpg accepts postgresql:// DSN strings; credentials never appear in logs
    # because asyncpg redacts the DSN in tracebacks.
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


async def init_pool() -> Pool:
    """Create and store the global asyncpg connection pool.

    Safe to call multiple times — returns the existing pool on subsequent calls.
    """
    global _pool
    if _pool is not None:
        return _pool

    min_size = int(os.environ.get("DB_MIN_CONNECTIONS", "2"))
    max_size = int(os.environ.get("DB_MAX_CONNECTIONS", "10"))

    _pool = await asyncpg.create_pool(
        dsn=_dsn(),
        min_size=min_size,
        max_size=max_size,
    )
    return _pool


async def get_pool() -> Pool:
    """Return the active pool, raising if not yet initialised."""
    if _pool is None:
        raise RuntimeError(
            "Database pool has not been initialised. Call init_pool() at application startup."
        )
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool. Call at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """Async context manager that yields a connection from the pool.

    Usage::

        async with acquire() as conn:
            row = await conn.fetchrow("SELECT 1")
    """
    pool = await get_pool()
    async with pool.acquire() as connection:
        yield connection
