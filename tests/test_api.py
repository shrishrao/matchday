"""Tests for the API's routes, input validation and error handling."""

from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

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


# ===== Server metrics =====
def queries_after(client, path):
    """Return how many database queries one request added."""
    before = client.get("/internal/metrics").json()["db_queries_total"]
    client.get(path)
    return client.get("/internal/metrics").json()["db_queries_total"] - before


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", 1),
        (f"/matches/{MATCH_ID}", 1),
        (f"/matches/{MATCH_ID}/feed", 2),
        (f"/matches/{MATCH_ID}/stats", 2),
        (f"/matches/{UNKNOWN_MATCH}/stats", 1),
        ("/matches/0", 0),
        (f"/matches/{MATCH_ID}/feed?limit=0", 0),
        ("/internal/metrics", 0),
    ],
)
def test_metrics_count_each_database_query(client, path, expected):
    assert queries_after(client, path) == expected


def test_metrics_report_pool_pressure(client):
    pool = client.get("/internal/metrics").json()["pool"]
    assert set(pool) == {"size", "available", "waiting", "failed_requests"}
    assert pool["size"] >= 1
    assert pool["waiting"] >= 0


def test_metrics_count_requests_that_could_not_get_a_connection(test_settings):
    # A one-connection pool that is held busy makes the next request time out waiting.
    tight = test_settings.model_copy(update={"pool_min_size": 1, "pool_max_size": 1, "pool_timeout_seconds": 0.2})
    with TestClient(create_app(tight)) as tight_client:
        pool = tight_client.app.state.pool
        with pool.connection():
            assert tight_client.get("/health").status_code == 503
        failed = tight_client.get("/internal/metrics").json()["pool"]["failed_requests"]
    assert failed == 1


def test_metrics_answer_while_every_route_thread_is_busy(test_settings):
    # Hold the only pooled connection so routes queue, then read metrics: it must not queue.
    import concurrent.futures
    import time

    tight = test_settings.model_copy(update={"pool_min_size": 1, "pool_max_size": 1, "pool_timeout_seconds": 3})
    with TestClient(create_app(tight)) as tight_client:
        with tight_client.app.state.pool.connection():
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                waiting = [pool.submit(tight_client.get, "/health") for _ in range(4)]
                time.sleep(0.5)
                started = time.monotonic()
                metrics = tight_client.get("/internal/metrics")
                elapsed = time.monotonic() - started
                waiting_now = metrics.json()["pool"]["waiting"]
        concurrent.futures.wait(waiting)
    assert metrics.status_code == 200
    assert elapsed < 1.0
    assert waiting_now >= 1


def test_metrics_report_that_cache_is_not_measured_when_off(client):
    metrics = client.get("/internal/metrics").json()
    assert metrics["cache"] == {"enabled": False, "hits": None, "misses": None, "errors": None}
    assert metrics["protections"] == {
        "cache": False, "stampede_lock": False, "rate_limit": False, "load_shedding": False
    }


def test_metrics_count_queries_from_concurrent_requests(client):
    import concurrent.futures

    before = client.get("/internal/metrics").json()["db_queries_total"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: client.get(f"/matches/{MATCH_ID}").status_code, range(40)))
    after = client.get("/internal/metrics").json()["db_queries_total"]
    assert statuses == [200] * 40
    assert after - before == 40


# ===== Database failures =====
def kill_api_connections(connection):
    """Terminate every other session on the test database, as a database restart would."""
    connection.execute(
        """
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
        """
    )
    connection.commit()


def test_small_pool_recovers_at_once_when_connections_are_killed(test_settings, connection):
    with TestClient(create_app(test_settings)) as fresh_client:
        assert fresh_client.get("/health").status_code == 200
        kill_api_connections(connection)
        statuses = [fresh_client.get("/health").status_code for _ in range(5)]
    assert statuses == [200] * 5


def test_full_pool_recovers_within_seconds_when_connections_are_killed(test_settings, connection):
    # A pool full of dead connections is checked one at a time with growing waits, so the
    # first requests can time out (503) before a healthy connection is found.
    import concurrent.futures
    import time

    with TestClient(create_app(test_settings)) as fresh_client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: fresh_client.get(f"/matches/{MATCH_ID}"), range(40)))
        kill_api_connections(connection)

        responses = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = fresh_client.get("/health")
            responses.append(response)
            if response.status_code == 200:
                break
        later = [fresh_client.get("/health").status_code for _ in range(5)]

    assert responses[-1].status_code == 200
    assert all(r.status_code == 503 and r.json() == {"detail": "Database unavailable"} for r in responses[:-1])
    assert later == [200] * 5


@pytest.mark.parametrize(
    "failure",
    [PoolTimeout("secret pool detail"), psycopg.OperationalError("secret database detail")],
)
def test_database_failure_returns_503_without_details(test_settings, failure, monkeypatch):
    @contextmanager
    def failing_connection():
        raise failure
        yield

    with TestClient(create_app(test_settings)) as failing_client:
        monkeypatch.setattr(failing_client.app.state.pool, "connection", failing_connection)
        response = failing_client.get("/health")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert "secret" not in response.text


def test_unexpected_error_does_not_expose_details(test_settings, monkeypatch):
    @contextmanager
    def failing_connection():
        raise RuntimeError("secret internal detail")
        yield

    with TestClient(create_app(test_settings), raise_server_exceptions=False) as failing_client:
        monkeypatch.setattr(failing_client.app.state.pool, "connection", failing_connection)
        response = failing_client.get("/health")
    assert response.status_code == 500
    assert "secret" not in response.text


# ===== Connection borrowing (D39) =====
def test_no_route_borrows_its_connection_through_a_yield_dependency():
    # A sync yield dependency needs a second worker thread to return its connection. Under
    # overload every thread waits for a connection, so none can be returned (Stage 7 finding).
    import inspect

    from fastapi.routing import APIRoute

    for route in create_app().routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                call = dependency.call
                assert not (inspect.isgeneratorfunction(call) or inspect.isasyncgenfunction(call)), route.path
