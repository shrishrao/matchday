"""Turn raw replay records into one structured result. This module does not import Locust.

Every number here comes from a real run's records; nothing is estimated or filled in.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 1
DISCLAIMER = (
    "Traffic is simulated. StatsBomb provides the match events, not platform traffic. "
    "Latency is measured by the load generator on the same computer as the API."
)


# ===== Result format =====
class StrictModel(BaseModel):
    """A model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class LatencySummary(StrictModel):
    """Request counts and response times in milliseconds. None means there were no requests."""

    requests: int
    failures: int
    error_rate: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None


class SecondRow(StrictModel):
    """What happened in one second of the replay."""

    second: int
    users_target: int
    users_actual: int
    requests: int
    failures: int
    p50_ms: float | None
    p95_ms: float | None
    db_queries: int | None


class DatabaseSummary(StrictModel):
    """Statements counted by the API during the run."""

    queries: int | None
    queries_per_request: float | None


class CacheSummary(StrictModel):
    """Cache use. None means not measured, because no cache was running."""

    enabled: bool
    hits: int | None
    misses: int | None
    hit_rate: float | None


class RunResult(StrictModel):
    """One complete replay run."""

    schema_version: Literal[1]
    run_id: str
    created_at: str
    disclaimer: str
    settings: dict
    environment: dict
    duration_seconds: int
    request_rate_per_second: float
    overall: LatencySummary
    endpoints: dict[str, LatencySummary]
    database: DatabaseSummary
    cache: CacheSummary
    follows_timeline: bool
    seconds: list[SecondRow]


# ===== Calculations =====
def percentile(values: Sequence[float], share: float) -> float | None:
    """Return the nearest-rank percentile, which is always a real observed value."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(share * len(ordered)))
    return round(ordered[rank - 1], 1)


def summarize_requests(records: Sequence[Mapping]) -> LatencySummary:
    """Summarize request records into counts, error rate and response-time percentiles."""
    times = [record["response_time_ms"] for record in records]
    failures = sum(1 for record in records if record["failed"])
    return LatencySummary(
        requests=len(records),
        failures=failures,
        error_rate=round(failures / len(records), 4) if records else None,
        p50_ms=percentile(times, 0.50),
        p95_ms=percentile(times, 0.95),
        p99_ms=percentile(times, 0.99),
        max_ms=round(max(times), 1) if times else None,
    )


def counter_at(samples: Sequence[Mapping], moment: float) -> int | None:
    """Return the last counter reading taken at or before a moment, or None if there is none."""
    readings = [sample["db_queries_total"] for sample in samples if sample["time"] <= moment]
    return readings[-1] if readings else None


def counter_delta(samples: Sequence[Mapping], start: float, end: float) -> int | None:
    """Return how much the counter rose between two moments, or None if either is unknown."""
    before, after = counter_at(samples, start), counter_at(samples, end)
    return None if before is None or after is None else after - before


def tick_windows(trace: Sequence[Mapping]) -> list[tuple[float, float]]:
    """Return each tick's time window, from its own time to the next tick's.

    Ticks drift slightly from exact seconds, so windows follow the real tick times. This way
    a skipped second loses no requests and every request falls in exactly one window.
    """
    times = [point["time"] for point in trace]
    return list(zip(times, times[1:] + [times[-1] + 1.0]))


def bucket_seconds(
    records: Sequence[Mapping], trace: Sequence[Mapping], samples: Sequence[Mapping]
) -> list[SecondRow]:
    """Build one row per tick, grouping requests by the window they finished in."""
    rows = []
    for point, (start, end) in zip(trace, tick_windows(trace)):
        summary = summarize_requests([r for r in records if start <= r["end_time"] < end])
        rows.append(
            SecondRow(
                second=point["second"],
                users_target=point["target"],
                users_actual=point["actual"],
                requests=summary.requests,
                failures=summary.failures,
                p50_ms=summary.p50_ms,
                p95_ms=summary.p95_ms,
                db_queries=counter_delta(samples, start, end),
            )
        )
    return rows


# ===== Result =====
def build_result(
    *,
    run_id: str,
    created_at: str,
    settings: dict,
    environment: dict,
    records: Sequence[Mapping],
    trace: Sequence[Mapping],
    samples: Sequence[Mapping],
    follows_timeline: bool,
) -> RunResult:
    """Combine a run's request records, user trace and server counter readings."""
    if not trace:
        raise ValueError("The run has no user trace, so it cannot be summarized.")
    windows = tick_windows(trace)
    duration = round(windows[-1][1] - windows[0][0])
    overall = summarize_requests(records)

    names = sorted({record["name"] for record in records})
    endpoints = {name: summarize_requests([r for r in records if r["name"] == name]) for name in names}

    queries = None
    if len(samples) >= 2:
        queries = samples[-1]["db_queries_total"] - samples[0]["db_queries_total"]
    per_request = round(queries / overall.requests, 3) if queries is not None and overall.requests else None

    cache = samples[-1]["cache"] if samples else {"enabled": False, "hits": None, "misses": None}
    looked_up = (cache["hits"] or 0) + (cache["misses"] or 0)
    hit_rate = round(cache["hits"] / looked_up, 4) if cache["enabled"] and looked_up else None

    return RunResult(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        created_at=created_at,
        disclaimer=DISCLAIMER,
        settings=settings,
        environment=environment,
        duration_seconds=duration,
        request_rate_per_second=round(overall.requests / duration, 2),
        overall=overall,
        endpoints=endpoints,
        database=DatabaseSummary(queries=queries, queries_per_request=per_request),
        cache=CacheSummary(enabled=cache["enabled"], hits=cache["hits"], misses=cache["misses"], hit_rate=hit_rate),
        follows_timeline=follows_timeline,
        seconds=bucket_seconds(records, trace, samples),
    )
