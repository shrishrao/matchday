"""The database connection pool. Routes borrow from it inside their own thread (see app.main)."""

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
