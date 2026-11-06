"""The database connection pool, and the request dependency that borrows from it."""

from collections.abc import Iterator

import psycopg
from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings


# ===== Connection pool =====
def create_pool(settings: Settings) -> ConnectionPool:
    """Build a closed pool that tests each connection before lending it, so a database
    restart does not leave requests holding dead connections."""
    return ConnectionPool(
        conninfo=settings.conninfo(),
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        timeout=settings.pool_timeout_seconds,
        kwargs={"row_factory": dict_row},
        check=ConnectionPool.check_connection,
        open=False,
    )


# ===== Request dependency =====
def get_connection(request: Request) -> Iterator[psycopg.Connection]:
    """Lend a connection for one request, returning it to the pool afterwards."""
    with request.app.state.pool.connection() as connection:
        yield connection
