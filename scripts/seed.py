"""Load repeatable placeholder data. Run with: python -m scripts.seed

Everything here is made up. Stage 3 replaces the match and events with real StatsBomb data.
Fan reactions stay generated, because StatsBomb provides match events, not platform traffic.
"""

import argparse
import random
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from app.config import PROJECT_ROOT, Settings

SCHEMA_PATH = Path(PROJECT_ROOT) / "app" / "schema.sql"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

DEFAULT_REACTIONS = 1_000_000
RANDOM_SEED = 2022
FAN_COUNT = 50_000
LAST_MINUTE = 95
SPIKE_WEIGHT = 25

# ===== Placeholder match =====
MATCH_ID = 1
HOME_TEAM = "Placeholder United"
AWAY_TEAM = "Sample City"
MATCH = (
    MATCH_ID,
    HOME_TEAM,
    AWAY_TEAM,
    "Placeholder Cup",
    datetime(2000, 1, 1, 15, 0, tzinfo=timezone.utc),
    "placeholder",
)
EVENTS = (
    (0, 0, "kick_off", None, "Placeholder event: kick-off"),
    (23, 10, "goal", HOME_TEAM, "Placeholder event: home goal"),
    (45, 30, "half_time", None, "Placeholder event: half-time"),
    (46, 0, "second_half", None, "Placeholder event: second half begins"),
    (67, 45, "goal", AWAY_TEAM, "Placeholder event: away goal"),
    (88, 5, "goal", HOME_TEAM, "Placeholder event: home goal"),
    (93, 0, "full_time", None, "Placeholder event: full-time"),
)
SPIKE_MINUTES = frozenset(event[0] for event in EVENTS if event[2] == "goal")


# ===== Data generation =====
def generate_reactions(count: int, seed: int = RANDOM_SEED) -> Iterator[tuple[int, int, int, str]]:
    """Yield the same fan reactions for the same inputs, with more of them around goals."""
    if count < 1:
        raise ValueError("count must be at least 1")
    rng = random.Random(seed)
    minutes = range(LAST_MINUTE + 1)
    weights = [SPIKE_WEIGHT if minute in SPIKE_MINUTES else 1 for minute in minutes]
    chosen_minutes = rng.choices(minutes, weights=weights, k=count)
    reaction_types = rng.choices(("cheer", "groan", "gasp"), weights=(6, 3, 1), k=count)
    for minute, reaction_type in zip(chosen_minutes, reaction_types):
        yield MATCH_ID, minute, rng.randint(1, FAN_COUNT), reaction_type


# ===== Database loading =====
def require_local_host(settings: Settings) -> None:
    """Refuse to run against a remote database, because seeding erases existing data."""
    if settings.postgres_host not in LOCAL_HOSTS:
        raise ValueError(f"Refusing to seed non-local host: {settings.postgres_host}")


def apply_schema(connection: psycopg.Connection) -> None:
    """Create any tables and indexes that do not exist yet."""
    connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def seed_database(
    connection: psycopg.Connection, reactions: int = DEFAULT_REACTIONS, seed: int = RANDOM_SEED
) -> None:
    """Replace all data with the placeholder match, events and generated reactions."""
    apply_schema(connection)
    connection.execute("TRUNCATE matches, match_events, fan_reactions RESTART IDENTITY")
    connection.execute(
        """
        INSERT INTO matches (id, home_team, away_team, competition, kickoff_at, data_source)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        MATCH,
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO match_events (match_id, minute, second, event_type, team, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [(MATCH_ID, *event) for event in EVENTS],
        )
        with cursor.copy(
            "COPY fan_reactions (match_id, minute, fan_id, reaction_type) FROM STDIN"
        ) as copy:
            for row in generate_reactions(reactions, seed):
                copy.write_row(row)
    connection.execute("ANALYZE matches, match_events, fan_reactions")


# ===== Command line =====
def main() -> int:
    """Seed the database named in .env and report the row counts."""
    parser = argparse.ArgumentParser(description="Load repeatable placeholder data.")
    parser.add_argument("--reactions", type=int, default=DEFAULT_REACTIONS)
    arguments = parser.parse_args()
    if arguments.reactions < 1:
        parser.error("--reactions must be at least 1")

    settings = Settings()
    require_local_host(settings)
    with psycopg.connect(settings.conninfo()) as connection:
        seed_database(connection, arguments.reactions)
        for table in ("matches", "match_events", "fan_reactions"):
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
