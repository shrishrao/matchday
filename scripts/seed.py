"""Load the real match and generated reactions. Run with: python -m scripts.seed

The match and its events are real, from StatsBomb. Fan reactions are generated, because
StatsBomb provides match events, not platform traffic. Seeding erases existing data.
"""

import argparse
import random
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg

from app.config import PROJECT_ROOT, Settings
from app.timeline import load_sample, played_clock

SCHEMA_PATH = Path(PROJECT_ROOT) / "app" / "schema.sql"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

DEFAULT_REACTIONS = 1_000_000
RANDOM_SEED = 2022
FAN_COUNT = 50_000
SPIKE_WEIGHT = 25

# ===== Real match data =====
SAMPLE = load_sample()
MATCH_ID = SAMPLE.match.id
CLOCK = played_clock(SAMPLE)
LAST_MINUTE = CLOCK[-1][1] // 60
SPIKE_MINUTES = frozenset(
    played // 60
    for event, played in CLOCK
    if event.kind in ("goal", "shootout_goal", "shootout_miss")
)


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
    """Replace the tables, so that schema changes always take effect."""
    connection.execute("DROP TABLE IF EXISTS fan_reactions, match_events, matches")
    connection.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def seed_database(
    connection: psycopg.Connection, reactions: int = DEFAULT_REACTIONS, seed: int = RANDOM_SEED
) -> None:
    """Replace all data with the real match, its key events, and generated reactions."""
    apply_schema(connection)
    match = SAMPLE.match
    connection.execute(
        """
        INSERT INTO matches
            (id, home_team, away_team, competition, season, match_date,
             home_score, away_score, data_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'statsbomb')
        """,
        (
            match.id,
            match.home_team,
            match.away_team,
            match.competition,
            match.season,
            match.match_date,
            match.home_score,
            match.away_score,
        ),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO match_events
                (match_id, period, minute, second, clock_seconds, event_type, team, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    match.id,
                    event.period,
                    event.minute,
                    event.second,
                    played,
                    event.kind,
                    event.team,
                    event.description,
                )
                for event, played in CLOCK
            ],
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
    parser = argparse.ArgumentParser(description="Load the real match and generated reactions.")
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
