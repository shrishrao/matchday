"""Server-side counters, shared by every request in this API process."""

import threading


# ===== Counters =====
class Counters:
    """Thread-safe running totals. Routes run in a thread pool, so updates are locked."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db_queries = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_errors = 0

    def add_query(self) -> None:
        """Record one SQL statement sent by a route."""
        with self._lock:
            self._db_queries += 1

    def add_cache_hit(self) -> None:
        """Record a request answered from Redis."""
        with self._lock:
            self._cache_hits += 1

    def add_cache_miss(self) -> None:
        """Record a request that found nothing in Redis and went to Postgres."""
        with self._lock:
            self._cache_misses += 1

    def add_cache_error(self) -> None:
        """Record a Redis failure or a damaged cache entry."""
        with self._lock:
            self._cache_errors += 1

    def snapshot(self, cache_enabled: bool) -> dict:
        """Return the current totals. With the cache off, cache counts are None: not measured."""
        with self._lock:
            if cache_enabled:
                cache = {
                    "enabled": True,
                    "hits": self._cache_hits,
                    "misses": self._cache_misses,
                    "errors": self._cache_errors,
                }
            else:
                cache = {"enabled": False, "hits": None, "misses": None, "errors": None}
            return {"db_queries_total": self._db_queries, "cache": cache}


COUNTERS = Counters()
