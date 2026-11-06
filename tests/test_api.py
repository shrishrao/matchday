"""Tests for the API's routes, input validation and error handling."""

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app.db import get_connection
from app.main import MAX_BIGINT, create_app
from scripts.seed import MATCH_ID, SAMPLE
from tests.conftest import TEST_REACTIONS

pytestmark = pytest.mark.integration
UNKNOWN_MATCH = 999_999


# ===== Health and match =====
def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_match_is_the_real_final(client):
    response = client.get(f"/matches/{MATCH_ID}")
    assert response.status_code == 200
    match = response.json()
    assert match["data_source"] == "statsbomb"
    assert (match["home_team"], match["home_score"]) == ("Argentina", 3)
    assert (match["away_team"], match["away_score"]) == ("France", 3)


@pytest.mark.parametrize("suffix", ["", "/feed", "/stats"])
def test_unknown_match_returns_404(client, suffix):
    assert client.get(f"/matches/{UNKNOWN_MATCH}{suffix}").status_code == 404


@pytest.mark.parametrize("suffix", ["", "/feed", "/stats"])
@pytest.mark.parametrize(
    "bad_id", ["0", "-1", "abc", "1.5", str(MAX_BIGINT + 1), "1;DROP TABLE matches"]
)
def test_invalid_match_id_returns_422(client, bad_id, suffix):
    assert client.get(f"/matches/{bad_id}{suffix}").status_code == 422


def test_largest_valid_match_id_is_not_a_validation_error(client):
    assert client.get(f"/matches/{MAX_BIGINT}").status_code == 404


# ===== Feed =====
def test_feed_returns_all_events_in_true_time_order(client):
    events = client.get(f"/matches/{MATCH_ID}/feed").json()["events"]
    clock = [event["clock_seconds"] for event in events]
    assert len(events) == len(SAMPLE.events)
    assert clock == sorted(clock)


def test_feed_keeps_overlapping_minutes_in_match_order(client):
    # The first half ends at minute 52, after the second half's stated start at minute 45.
    events = client.get(f"/matches/{MATCH_ID}/feed").json()["events"]
    order = [(event["period"], event["event_type"]) for event in events]
    assert order.index((1, "period_end")) + 1 == order.index((2, "period_start"))
    assert [event["period"] for event in events] == sorted(event["period"] for event in events)


def test_feed_respects_limit(client):
    events = client.get(f"/matches/{MATCH_ID}/feed", params={"limit": 2}).json()["events"]
    assert len(events) == 2


def test_feed_returns_only_events_after_the_clock_time(client):
    params = {"after_seconds": 3600}
    events = client.get(f"/matches/{MATCH_ID}/feed", params=params).json()["events"]
    assert events
    assert all(event["clock_seconds"] > 3600 for event in events)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "many"},
        {"after_seconds": -1},
        {"after_seconds": 14401},
        {"after_seconds": "1 OR 1=1"},
    ],
)
def test_feed_rejects_invalid_parameters(client, params):
    assert client.get(f"/matches/{MATCH_ID}/feed", params=params).status_code == 422


@pytest.mark.parametrize("params", [{"limit": 1}, {"limit": 100}, {"after_seconds": 0}, {"after_seconds": 14400}])
def test_feed_accepts_boundary_parameters(client, params):
    assert client.get(f"/matches/{MATCH_ID}/feed", params=params).status_code == 200


# ===== Slow stats =====
def test_stats_totals_match_seeded_reactions(client):
    minutes = client.get(f"/matches/{MATCH_ID}/stats").json()["minutes"]
    assert sum(minute["total"] for minute in minutes) == TEST_REACTIONS


def test_stats_breakdown_is_consistent(client):
    minutes = client.get(f"/matches/{MATCH_ID}/stats").json()["minutes"]
    for minute in minutes:
        assert minute["cheers"] + minute["groans"] + minute["gasps"] == minute["total"]
        assert 1 <= minute["unique_fans"] <= minute["total"]


# ===== Database failures =====
def test_api_recovers_when_pool_connections_are_killed(client, connection):
    for _ in range(3):
        assert client.get("/health").status_code == 200
    connection.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
        """
    )
    connection.commit()
    statuses = [client.get("/health").status_code for _ in range(5)]
    assert statuses == [200] * 5


@pytest.mark.parametrize(
    "failure",
    [PoolTimeout("secret pool detail"), psycopg.OperationalError("secret database detail")],
)
def test_database_failure_returns_503_without_details(test_settings, failure):
    def failing_connection():
        raise failure
        yield

    app = create_app(test_settings)
    app.dependency_overrides[get_connection] = failing_connection
    with TestClient(app) as failing_client:
        response = failing_client.get("/health")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert "secret" not in response.text


def test_unexpected_error_does_not_expose_details(test_settings):
    def failing_connection():
        raise RuntimeError("secret internal detail")
        yield

    app = create_app(test_settings)
    app.dependency_overrides[get_connection] = failing_connection
    with TestClient(app, raise_server_exceptions=False) as failing_client:
        response = failing_client.get("/health")
    assert response.status_code == 500
    assert "secret" not in response.text
