"""All SQL used by the API. Values are always passed as parameters, never joined into text.

Every statement goes through run_query, so the query counter sees all of them.
The pool's own connection checks are not counted, because they are not route work.
"""

import psycopg

from app.metrics import COUNTERS

# ===== Deliberately slow query =====
# Reads every reaction for the match, then sorts each minute's fans to count distinct values.
# Stage 7 onward protects this query; it must stay slow so the comparison is real.
MATCH_STATS_SQL = """
    SELECT
        minute,
        count(*) AS total,
        count(*) FILTER (WHERE reaction_type = 'cheer') AS cheers,
        count(*) FILTER (WHERE reaction_type = 'groan') AS groans,
        count(*) FILTER (WHERE reaction_type = 'gasp') AS gasps,
        count(DISTINCT fan_id) AS unique_fans
    FROM fan_reactions
    WHERE match_id = %(match_id)s
    GROUP BY minute
    ORDER BY minute
"""


# ===== Counted execution =====
def run_query(connection: psycopg.Connection, sql: str, params: dict | None = None) -> psycopg.Cursor:
    """Count one statement, then send it to the database."""
    COUNTERS.add_query()
    return connection.execute(sql, params)


# ===== Fast queries =====
def ping(connection: psycopg.Connection) -> None:
    """Run the smallest possible query to prove the database answers."""
    run_query(connection, "SELECT 1")


def get_match(connection: psycopg.Connection, match_id: int) -> dict | None:
    """Return one match, or None if it does not exist."""
    return run_query(
        connection,
        """
        SELECT id, home_team, away_team, competition, season, match_date,
               home_score, away_score, data_source
        FROM matches
        WHERE id = %(match_id)s
        """,
        {"match_id": match_id},
    ).fetchone()


def get_feed(
    connection: psycopg.Connection, match_id: int, after_seconds: int | None, limit: int
) -> list[dict]:
    """Return a match's events in true time order, optionally only those after a clock time."""
    return run_query(
        connection,
        """
        SELECT id, period, minute, second, clock_seconds, event_type, team, description
        FROM match_events
        WHERE match_id = %(match_id)s
          AND (%(after_seconds)s::integer IS NULL OR clock_seconds > %(after_seconds)s::integer)
        ORDER BY clock_seconds, period, id
        LIMIT %(limit)s
        """,
        {"match_id": match_id, "after_seconds": after_seconds, "limit": limit},
    ).fetchall()


# ===== Slow query =====
def get_match_stats(connection: psycopg.Connection, match_id: int) -> list[dict]:
    """Run the deliberately slow per-minute reaction summary."""
    return run_query(connection, MATCH_STATS_SQL, {"match_id": match_id}).fetchall()
