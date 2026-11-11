"""Tests for the Redis response cache: hits, misses, expiry, invalidation and Redis failures.

Each test uses its own key prefix, so it never touches the cache of an API you are running.
"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.cache import CacheStatus, ResponseCache, create_client
from app.config import Settings
from app.main import CACHE_HEADER, create_app
from scripts import seed

MATCH_ID = 3869685
OTHER_MATCH_ID = 1
PATHS = {
    "match": f"/matches/{MATCH_ID}",
    "feed": f"/matches/{MATCH_ID}/feed",
    "stats": f"/matches/{MATCH_ID}/stats",
}


# ===== Fixtures =====
@pytest.fixture
def cache_settings(test_settings):
    """Test settings with the cache on, under a prefix unique to this test."""
    return test_settings.model_copy(
        update={"cache_enabled": True, "cache_prefix": f"matchday-test:{uuid.uuid4().hex}"}
    )


@pytest.fixture
def redis_cache(cache_settings):
    """A direct handle on this test's cache, emptied afterwards."""
    cache = ResponseCache(create_client(cache_settings), cache_settings.cache_prefix)
    yield cache
    cache.clear()
    cache.close()


@pytest.fixture
def cached_client(cache_settings, redis_cache):
    """The API with the cache on."""
    with TestClient(create_app(cache_settings)) as test_client:
        yield test_client


def metrics(client) -> dict:
    """Read the API's counters."""
    return client.get("/internal/metrics").json()


def queries_for(client, path: str) -> tuple[int, dict]:
    """Return how many database queries one request caused, and the response."""
    before = metrics(client)["db_queries_total"]
    response = client.get(path)
    return metrics(client)["db_queries_total"] - before, response


# ===== Hits and misses =====
@pytest.mark.parametrize("path", PATHS.values())
def test_first_request_misses_then_the_next_hits(cached_client, path):
    first = cached_client.get(path)
    second = cached_client.get(path)
    assert first.status_code == second.status_code == 200
    assert first.headers[CACHE_HEADER] == "MISS"
    assert second.headers[CACHE_HEADER] == "HIT"
    assert second.json() == first.json()


@pytest.mark.parametrize("path", PATHS.values())
def test_a_hit_sends_no_database_query(cached_client, path):
    missed, _ = queries_for(cached_client, path)
    hit, response = queries_for(cached_client, path)
    assert missed >= 1
    assert hit == 0
    assert response.headers[CACHE_HEADER] == "HIT"


def test_a_hit_does_not_wait_for_a_database_connection(cache_settings, redis_cache):
    # Hold the only pooled connection. A hit must still answer; a miss must time out with 503.
    tight = cache_settings.model_copy(
        update={"pool_min_size": 1, "pool_max_size": 1, "pool_timeout_seconds": 0.5}
    )
    with TestClient(create_app(tight)) as tight_client:
        assert tight_client.get(PATHS["stats"]).status_code == 200
        with tight_client.app.state.pool.connection():
            hit = tight_client.get(PATHS["stats"])
            miss = tight_client.get(PATHS["match"])
    assert hit.status_code == 200
    assert hit.headers[CACHE_HEADER] == "HIT"
    assert miss.status_code == 503


def test_metrics_count_hits_and_misses(cached_client):
    before = metrics(cached_client)
    cached_client.get(PATHS["stats"])
    cached_client.get(PATHS["stats"])
    cached_client.get(PATHS["stats"])
    after = metrics(cached_client)
    assert after["cache"]["enabled"] is True
    assert after["protections"]["cache"] is True
    assert after["cache"]["misses"] - before["cache"]["misses"] == 1
    assert after["cache"]["hits"] - before["cache"]["hits"] == 2


def test_feed_pages_are_cached_separately(cached_client, redis_cache):
    full = cached_client.get(PATHS["feed"])
    page = cached_client.get(PATHS["feed"], params={"limit": 3})
    later = cached_client.get(PATHS["feed"], params={"after_seconds": 3600, "limit": 3})
    assert page.headers[CACHE_HEADER] == later.headers[CACHE_HEADER] == "MISS"
    assert len(page.json()["events"]) == 3
    assert page.json() != later.json()
    assert len(full.json()["events"]) > 3
    assert redis_cache.client.exists(
        redis_cache.feed_key(MATCH_ID, None, 50),
        redis_cache.feed_key(MATCH_ID, None, 3),
        redis_cache.feed_key(MATCH_ID, 3600, 3),
    ) == 3


def test_entries_are_stored_with_their_ttl(cached_client, redis_cache, cache_settings):
    cached_client.get(PATHS["stats"])
    cached_client.get(PATHS["feed"])
    stats_ttl = redis_cache.client.ttl(redis_cache.stats_key(MATCH_ID))
    feed_ttl = redis_cache.client.ttl(redis_cache.feed_key(MATCH_ID, None, 50))
    assert 0 < stats_ttl <= cache_settings.cache_ttl_stats_seconds
    assert 0 < feed_ttl <= cache_settings.cache_ttl_feed_seconds


# ===== What is never cached =====
def test_unknown_match_is_not_cached(cached_client, redis_cache):
    assert cached_client.get(f"/matches/{OTHER_MATCH_ID}/stats").status_code == 404
    assert cached_client.get(f"/matches/{OTHER_MATCH_ID}/stats").status_code == 404
    assert list(redis_cache.client.scan_iter(match=f"{redis_cache.prefix}:*")) == []


@pytest.mark.parametrize("path", ["/matches/0", f"/matches/{MATCH_ID}/feed?limit=0", "/matches/abc/stats"])
def test_invalid_input_is_rejected_before_the_cache(cached_client, path):
    before = metrics(cached_client)["cache"]
    assert cached_client.get(path).status_code == 422
    after = metrics(cached_client)["cache"]
    assert (after["hits"], after["misses"]) == (before["hits"], before["misses"])


def test_health_is_never_cached(cached_client):
    response = cached_client.get("/health")
    assert CACHE_HEADER not in response.headers


def test_cache_off_says_so(test_settings):
    # A fresh app: the shared client's pool may hold connections that earlier tests killed (D32).
    with TestClient(create_app(test_settings)) as off_client:
        response = off_client.get(PATHS["stats"])
    assert response.status_code == 200, response.text
    assert response.headers[CACHE_HEADER] == "OFF"


# ===== Expiry and invalidation =====
def test_entry_expires_after_its_ttl(cache_settings, redis_cache):
    short = cache_settings.model_copy(update={"cache_ttl_stats_seconds": 1})
    with TestClient(create_app(short)) as short_client:
        statuses = [short_client.get(PATHS["stats"]).headers[CACHE_HEADER] for _ in range(2)]
        time.sleep(1.3)
        statuses.append(short_client.get(PATHS["stats"]).headers[CACHE_HEADER])
    assert statuses == ["MISS", "HIT", "MISS"]


def test_changed_data_is_stale_until_invalidated(cached_client, redis_cache, connection):
    original = cached_client.get(PATHS["match"]).json()["home_team"]
    try:
        connection.execute("UPDATE matches SET home_team = 'Changed' WHERE id = %s", (MATCH_ID,))
        connection.commit()
        # Within the TTL, the cache still serves the old answer. This is the price of caching.
        assert cached_client.get(PATHS["match"]).json()["home_team"] == original
        assert redis_cache.invalidate_match(MATCH_ID) >= 1
        fresh = cached_client.get(PATHS["match"])
        assert fresh.headers[CACHE_HEADER] == "MISS"
        assert fresh.json()["home_team"] == "Changed"
    finally:
        connection.execute("UPDATE matches SET home_team = %s WHERE id = %s", (original, MATCH_ID))
        connection.commit()
        redis_cache.invalidate_match(MATCH_ID)


def test_invalidating_a_match_removes_all_its_entries(cached_client, redis_cache):
    for path in PATHS.values():
        cached_client.get(path)
    cached_client.get(PATHS["feed"], params={"limit": 5})
    assert redis_cache.invalidate_match(MATCH_ID) == 4
    assert [cached_client.get(path).headers[CACHE_HEADER] for path in PATHS.values()] == ["MISS"] * 3


def test_invalidating_one_match_leaves_others_alone(redis_cache):
    # Match 1's pattern must not catch match 10 or match 100.
    for match_id in (1, 10, 100):
        redis_cache.put(redis_cache.match_key(match_id), "{}", 60)
        redis_cache.put(redis_cache.stats_key(match_id), "{}", 60)
    assert redis_cache.invalidate_match(1) == 2
    remaining = sorted(redis_cache.client.scan_iter(match=f"{redis_cache.prefix}:*"))
    assert remaining == sorted(
        [redis_cache.match_key(10), redis_cache.stats_key(10), redis_cache.match_key(100), redis_cache.stats_key(100)]
    )


def test_clear_only_removes_keys_under_its_prefix(cache_settings, redis_cache):
    neighbour = ResponseCache(create_client(cache_settings), f"{cache_settings.cache_prefix}-other")
    try:
        neighbour.put(neighbour.stats_key(MATCH_ID), "{}", 60)
        redis_cache.put(redis_cache.stats_key(MATCH_ID), "{}", 60)
        assert redis_cache.clear() == 1
        assert neighbour.client.exists(neighbour.stats_key(MATCH_ID)) == 1
    finally:
        neighbour.clear()
        neighbour.close()


def test_seeding_clears_the_cache(cache_settings, redis_cache):
    redis_cache.put(redis_cache.stats_key(MATCH_ID), "{}", 60)
    assert seed.clear_cache(cache_settings) == "cache: removed 1 entries"
    assert redis_cache.client.exists(redis_cache.stats_key(MATCH_ID)) == 0


def test_seeding_still_finishes_when_redis_is_down(cache_settings):
    unreachable = cache_settings.model_copy(update={"redis_port": 1})
    assert "not reachable" in seed.clear_cache(unreachable)


# ===== Failures =====
def test_api_keeps_answering_when_redis_is_down(cache_settings):
    unreachable = cache_settings.model_copy(update={"redis_port": 1})
    with TestClient(create_app(unreachable)) as down_client:
        before = metrics(down_client)["cache"]["errors"]
        responses = [down_client.get(path) for path in PATHS.values()]
        after = metrics(down_client)["cache"]["errors"]
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert {r.headers[CACHE_HEADER] for r in responses} == {"UNAVAILABLE"}
    assert after - before == 3


def test_damaged_entry_is_replaced_with_a_fresh_answer(cached_client, redis_cache):
    redis_cache.put(redis_cache.stats_key(MATCH_ID), "not json", 60)
    response = cached_client.get(PATHS["stats"])
    assert response.status_code == 200
    assert response.headers[CACHE_HEADER] == "MISS"
    assert cached_client.get(PATHS["stats"]).headers[CACHE_HEADER] == "HIT"


def test_lookup_reports_unavailable_without_raising(cache_settings):
    broken = ResponseCache(create_client(cache_settings.model_copy(update={"redis_port": 1})), "matchday-test:x")
    assert broken.get("anything") == (None, CacheStatus.UNAVAILABLE)
    assert broken.put("anything", "{}", 5) is False
    broken.close()


# ===== Settings =====
def test_cache_needs_a_redis_password(test_settings):
    with pytest.raises(ValidationError, match="REDIS_PASSWORD"):
        Settings(**{**test_settings.model_dump(), "cache_enabled": True, "redis_password": None})


@pytest.mark.parametrize("prefix", ["matchday:*", "match?day", "", "Matchday", "matchday:", "a b"])
def test_prefix_cannot_contain_pattern_characters(test_settings, prefix):
    with pytest.raises(ValidationError):
        Settings(**{**test_settings.model_dump(), "cache_prefix": prefix})


@pytest.mark.parametrize("field", ["cache_ttl_match_seconds", "cache_ttl_feed_seconds", "cache_ttl_stats_seconds"])
@pytest.mark.parametrize("value", [0, 3601])
def test_ttl_must_be_reasonable(test_settings, field, value):
    with pytest.raises(ValidationError):
        Settings(**{**test_settings.model_dump(), field: value})


def test_cache_is_off_by_default(monkeypatch):
    monkeypatch.delenv("CACHE_ENABLED", raising=False)
    assert Settings(_env_file=None, postgres_user="u", postgres_password="p", postgres_db="d",
                    postgres_host="127.0.0.1", postgres_port=5432).cache_enabled is False


# ===== Redis memory limit =====
def test_redis_drops_least_recently_used_keys_when_full(redis_cache):
    # Many different feed queries could otherwise fill Redis's memory.
    assert redis_cache.client.config_get("maxmemory-policy")["maxmemory-policy"] == "allkeys-lru"
    assert int(redis_cache.client.config_get("maxmemory")["maxmemory"]) > 0


def test_a_broken_redis_costs_at_most_about_one_timeout(cache_settings):
    # redis-py retries 10 times by default, which made each request wait about 10 s.
    broken = ResponseCache(create_client(cache_settings.model_copy(update={"redis_port": 1})), "matchday-test:x")
    started = time.monotonic()
    broken.get("anything")
    elapsed = time.monotonic() - started
    broken.close()
    assert elapsed < cache_settings.redis_timeout_seconds * 3
