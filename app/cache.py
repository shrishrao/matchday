"""A Redis response cache for the match routes, used only when CACHE_ENABLED is true.

This is cache-aside: look in Redis first; on a miss, ask Postgres and store the answer
for a fixed time (its TTL). If Redis fails, the request falls back to Postgres, so the
cache can make the API faster but never takes it down.
"""

from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

import redis
from pydantic import BaseModel
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config import Settings
from app.metrics import COUNTERS

Model = TypeVar("Model", bound=BaseModel)
SCAN_BATCH = 500


# ===== Lookup outcomes =====
class CacheStatus(StrEnum):
    """What happened to one request, sent back in the X-Cache header."""

    HIT = "HIT"
    MISS = "MISS"
    OFF = "OFF"
    UNAVAILABLE = "UNAVAILABLE"


# ===== Redis client =====
def create_client(settings: Settings) -> redis.Redis:
    """Build a Redis client that gives up quickly, so a broken Redis cannot stall requests.

    redis-py retries a failed command 10 times by default. Here a failure falls straight
    back to Postgres instead, so the wait is at most one timeout.
    """
    password = settings.redis_password.get_secret_value() if settings.redis_password else None
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=password,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0),
    )


# ===== Cache =====
class ResponseCache:
    """Stores finished JSON responses under keys that start with one fixed prefix."""

    def __init__(self, client: redis.Redis, prefix: str) -> None:
        self.client = client
        self.prefix = prefix

    # ----- Keys -----
    def match_key(self, match_id: int) -> str:
        """Key for one match's details."""
        return f"{self.prefix}:match:{match_id}"

    def feed_key(self, match_id: int, after_seconds: int | None, limit: int) -> str:
        """Key for one page of a match's feed. Each query combination is cached separately."""
        after = "start" if after_seconds is None else after_seconds
        return f"{self.match_key(match_id)}:feed:{after}:{limit}"

    def stats_key(self, match_id: int) -> str:
        """Key for a match's per-minute stats."""
        return f"{self.match_key(match_id)}:stats"

    # ----- Reading and writing -----
    def get(self, key: str) -> tuple[str | None, CacheStatus]:
        """Return the stored JSON and HIT, or None and MISS, or None and UNAVAILABLE if Redis failed."""
        try:
            value = self.client.get(key)
        except redis.RedisError:
            COUNTERS.add_cache_error()
            return None, CacheStatus.UNAVAILABLE
        if value is None:
            COUNTERS.add_cache_miss()
            return None, CacheStatus.MISS
        COUNTERS.add_cache_hit()
        return value, CacheStatus.HIT

    def put(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Store JSON for a fixed time. A Redis failure is counted, not raised."""
        try:
            self.client.set(key, value, ex=ttl_seconds)
            return True
        except redis.RedisError:
            COUNTERS.add_cache_error()
            return False

    # ----- Invalidation -----
    def delete_matching(self, pattern: str) -> int:
        """Delete every key matching a pattern, a batch at a time, and return how many went."""
        deleted = 0
        batch: list[str] = []
        for key in self.client.scan_iter(match=pattern, count=SCAN_BATCH):
            batch.append(key)
            if len(batch) >= SCAN_BATCH:
                deleted += self.client.delete(*batch)
                batch = []
        if batch:
            deleted += self.client.delete(*batch)
        return deleted

    def invalidate_match(self, match_id: int) -> int:
        """Remove everything cached for one match: details, every feed page and the stats."""
        return self.client.delete(self.match_key(match_id)) + self.delete_matching(
            f"{self.match_key(match_id)}:*"
        )

    def clear(self) -> int:
        """Remove every key under this cache's prefix, and nothing else."""
        return self.delete_matching(f"{self.prefix}:*")

    def close(self) -> None:
        """Close the Redis connections."""
        self.client.close()


def create_cache(settings: Settings) -> ResponseCache | None:
    """Return a cache if CACHE_ENABLED is true, otherwise None."""
    if not settings.cache_enabled:
        return None
    return ResponseCache(create_client(settings), settings.cache_prefix)


# ===== Cache-aside =====
def cached(
    cache: ResponseCache | None,
    key: str,
    ttl_seconds: int,
    model: type[Model],
    load: Callable[[], dict],
) -> tuple[Model, CacheStatus]:
    """Return a response from the cache, or build it with load() and store it.

    load() is only called on a miss, so a hit never borrows a database connection.
    If load() raises (for example a 404), nothing is stored.
    """
    if cache is None:
        return model.model_validate(load()), CacheStatus.OFF

    stored, status = cache.get(key)
    if stored is not None:
        try:
            return model.model_validate_json(stored), CacheStatus.HIT
        except ValueError:
            # A damaged entry is treated as a miss and overwritten with a fresh answer.
            COUNTERS.add_cache_error()
            status = CacheStatus.MISS

    fresh = model.model_validate(load())
    if status is not CacheStatus.UNAVAILABLE:
        cache.put(key, fresh.model_dump_json(), ttl_seconds)
    return fresh, status
