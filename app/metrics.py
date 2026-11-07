"""Server-side counters, shared by every request in this API process."""

import threading


# ===== Counters =====
class Counters:
    """Thread-safe running totals. Routes run in a thread pool, so updates are locked."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._db_queries = 0

    def add_query(self) -> None:
        """Record one SQL statement sent by a route."""
        with self._lock:
            self._db_queries += 1

    def snapshot(self) -> dict:
        """Return the current totals. There is no cache yet, so cache counts are not measured."""
        with self._lock:
            return {
                "db_queries_total": self._db_queries,
                "cache": {"enabled": False, "hits": None, "misses": None},
            }


COUNTERS = Counters()
