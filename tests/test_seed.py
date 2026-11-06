"""Tests for repeatable seed data, the slow query's setup, and settings validation."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from scripts.explain_slow_query import explain_stats
from scripts.seed import (
    EVENTS,
    FAN_COUNT,
    LAST_MINUTE,
    MATCH_ID,
    SPIKE_MINUTES,
    generate_reactions,
    require_local_host,
    seed_database,
)
from tests.conftest import TEST_REACTIONS


# ===== Helpers =====
def table_fingerprint(connection) -> tuple:
    """Summarize the seeded tables, so that two loads can be compared."""
    return connection.execute(
        """
        SELECT
            (SELECT count(*) FROM matches),
            (SELECT count(*) FROM match_events),
            (SELECT count(*) FROM fan_reactions),
            (SELECT md5(string_agg(concat_ws(',', id, minute, fan_id, reaction_type), ';' ORDER BY id))
             FROM fan_reactions)
        """
    ).fetchone()


# ===== Generated data =====
def test_same_seed_gives_same_reactions():
    assert list(generate_reactions(500, seed=7)) == list(generate_reactions(500, seed=7))


def test_different_seed_gives_different_reactions():
    assert list(generate_reactions(500, seed=7)) != list(generate_reactions(500, seed=8))


def test_reactions_stay_within_valid_ranges():
    for match_id, minute, fan_id, reaction_type in generate_reactions(2_000):
        assert match_id == MATCH_ID
        assert 0 <= minute <= LAST_MINUTE
        assert 1 <= fan_id <= FAN_COUNT
        assert reaction_type in {"cheer", "groan", "gasp"}


def test_goal_minutes_have_more_reactions():
    minutes = [row[1] for row in generate_reactions(20_000)]
    busiest_quiet_minute = max(minutes.count(m) for m in range(LAST_MINUTE + 1) if m not in SPIKE_MINUTES)
    assert all(minutes.count(minute) > busiest_quiet_minute for minute in SPIKE_MINUTES)


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_reaction_count_is_rejected(count):
    with pytest.raises(ValueError):
        list(generate_reactions(count))


# ===== Safety and settings =====
def test_seeding_refuses_a_remote_database():
    with pytest.raises(ValueError, match="non-local"):
        require_local_host(Settings(postgres_host="db.example.com"))


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_seeding_allows_local_hosts(host):
    require_local_host(Settings(postgres_host=host))


@pytest.mark.parametrize(
    "override", [{"postgres_port": 0}, {"postgres_port": 70000}, {"pool_max_size": 0}, {"pool_timeout_seconds": 0}]
)
def test_invalid_settings_are_rejected(override):
    with pytest.raises(ValidationError):
        Settings(**override)


def test_settings_do_not_print_the_password():
    settings = Settings(postgres_password="visible-only-if-leaked")
    assert "visible-only-if-leaked" not in repr(settings)


# ===== Database =====
@pytest.mark.integration
def test_reseeding_gives_identical_data_without_duplicates(connection):
    seed_database(connection, reactions=TEST_REACTIONS)
    first = table_fingerprint(connection)
    seed_database(connection, reactions=TEST_REACTIONS)
    second = table_fingerprint(connection)
    assert first == second
    assert first[:3] == (1, len(EVENTS), TEST_REACTIONS)


@pytest.mark.integration
def test_slow_table_has_only_its_primary_key_index(connection):
    indexes = connection.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'fan_reactions'"
    ).fetchall()
    assert indexes == [("fan_reactions_pkey",)]


@pytest.mark.integration
def test_slow_query_scans_the_whole_table(connection):
    plan = "\n".join(explain_stats(connection))
    assert "Seq Scan on fan_reactions" in plan
