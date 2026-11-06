"""Show how Postgres runs the slow query. Run with: python -m scripts.explain_slow_query"""

import sys

import psycopg

from app.config import Settings
from app.queries import MATCH_STATS_SQL
from scripts.seed import MATCH_ID


# ===== Query plan =====
def explain_stats(connection: psycopg.Connection, match_id: int = MATCH_ID) -> list[str]:
    """Run the slow query with EXPLAIN ANALYZE and return the plan's lines."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"EXPLAIN (ANALYZE, BUFFERS) {MATCH_STATS_SQL}", {"match_id": match_id}
        )
        return [row[0] for row in cursor.fetchall()]


# ===== Command line =====
def main() -> int:
    """Print the plan for the database named in .env."""
    with psycopg.connect(Settings().conninfo()) as connection:
        print("\n".join(explain_stats(connection)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
