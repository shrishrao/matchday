"""Decide whether a run degraded, using thresholds fixed before any tuning (see DECISIONS.md D33)."""

import statistics
from collections.abc import Sequence

from loadgen.results import RunResult

FEED_ENDPOINT = "/matches/[id]/feed"
STATS_ENDPOINT = "/matches/[id]/stats"
FEED_P95_DEGRADED_MS = 500.0
ERROR_RATE_DEGRADED = 0.01
REQUIRED_REPEATS = 3


# ===== One run =====
def evaluate(result: RunResult) -> dict:
    """Return a run's key numbers, whether it degraded, and why."""
    feed = result.endpoints.get(FEED_ENDPOINT)
    feed_p95 = feed.p95_ms if feed else None
    stats = result.endpoints.get(STATS_ENDPOINT)
    error_rate = result.overall.error_rate
    reasons = []
    if feed_p95 is not None and feed_p95 >= FEED_P95_DEGRADED_MS:
        reasons.append(f"feed p95 {feed_p95} ms >= {FEED_P95_DEGRADED_MS:.0f} ms")
    if error_rate is not None and error_rate >= ERROR_RATE_DEGRADED:
        reasons.append(f"error rate {error_rate:.2%} >= {ERROR_RATE_DEGRADED:.0%}")
    return {
        "run_id": result.run_id,
        "base_users": result.settings.get("base_users"),
        "peak_users": result.settings.get("peak_users"),
        "requests": result.overall.requests,
        "request_rate_per_second": result.request_rate_per_second,
        "feed_p95_ms": feed_p95,
        "overall_p95_ms": result.overall.p95_ms,
        "stats_p95_ms": stats.p95_ms if stats else None,
        "error_rate": error_rate,
        "db_queries_per_request": result.database.queries_per_request,
        "cache_hit_rate": result.cache.hit_rate,
        "pool_waiting_max": result.pool.waiting_max if result.pool else None,
        "recovery_seconds": result.recovery_seconds,
        "degraded": bool(reasons),
        "reasons": reasons,
    }


# ===== Repeated runs =====
def spread(values: Sequence[float | None]) -> dict:
    """Return the mean, minimum, maximum and standard deviation of measured values."""
    measured = [value for value in values if value is not None]
    if not measured:
        return {"mean": None, "min": None, "max": None, "stdev": None, "runs": 0}
    return {
        "mean": round(statistics.fmean(measured), 4),
        "min": min(measured),
        "max": max(measured),
        "stdev": round(statistics.stdev(measured), 4) if len(measured) > 1 else None,
        "runs": len(measured),
    }


def summarize_repeats(evaluations: Sequence[dict]) -> dict:
    """Summarize repeated runs: whether every one degraded, and the spread of key numbers."""
    return {
        "runs": len(evaluations),
        "degraded_runs": sum(e["degraded"] for e in evaluations),
        "repeatable": len(evaluations) >= REQUIRED_REPEATS and all(e["degraded"] for e in evaluations),
        "feed_p95_ms": spread([e["feed_p95_ms"] for e in evaluations]),
        "error_rate": spread([e["error_rate"] for e in evaluations]),
        "request_rate_per_second": spread([e["request_rate_per_second"] for e in evaluations]),
        "pool_waiting_max": spread([e["pool_waiting_max"] for e in evaluations]),
        "recovery_seconds": spread([e.get("recovery_seconds") for e in evaluations]),
        "overall_p95_ms": spread([e.get("overall_p95_ms") for e in evaluations]),
        "stats_p95_ms": spread([e.get("stats_p95_ms") for e in evaluations]),
        "db_queries_per_request": spread([e.get("db_queries_per_request") for e in evaluations]),
        "cache_hit_rate": spread([e.get("cache_hit_rate") for e in evaluations]),
    }
