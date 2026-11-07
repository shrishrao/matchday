"""Tests for turning raw replay records into a structured result."""

import pytest
from pydantic import ValidationError

from app.timeline import serialize
from loadgen.results import (
    RunResult,
    build_result,
    counter_at,
    counter_delta,
    percentile,
    summarize_requests,
)

START = 1_000.0


# ===== Helpers =====
def request(name="/feed", end=START + 0.5, ms=10.0, failed=False):
    """Build one request record."""
    return {"name": name, "end_time": end, "response_time_ms": ms, "failed": failed}


def sample(time, queries, enabled=False, hits=None, misses=None):
    """Build one server counter reading."""
    return {"time": time, "db_queries_total": queries, "cache": {"enabled": enabled, "hits": hits, "misses": misses}}


def trace(seconds=3):
    """Build a user trace that starts at START."""
    return [{"second": s, "time": START + s, "target": 5, "actual": 5} for s in range(seconds)]


def result(records=(), samples=(), seconds=3, follows=True):
    """Build a result with fixed settings."""
    return build_result(
        run_id="run_test",
        created_at="2026-11-07T00:00:00+00:00",
        settings={"base_users": 5},
        environment={"os": "test"},
        records=list(records),
        trace=trace(seconds),
        samples=list(samples),
        follows_timeline=follows,
    )


# ===== Percentiles =====
@pytest.mark.parametrize(
    ("values", "share", "expected"),
    [
        ([], 0.5, None),
        ([7], 0.95, 7),
        ([1, 2, 3, 4], 0.5, 2),
        ([4, 3, 2, 1], 0.5, 2),
        (list(range(1, 101)), 0.95, 95),
        (list(range(1, 101)), 0.99, 99),
        (list(range(1, 21)), 0.95, 19),
        ([10, 1000], 0.95, 1000),
    ],
)
def test_percentile_uses_nearest_rank(values, share, expected):
    assert percentile(values, share) == expected


def test_percentile_is_always_an_observed_value():
    values = [3.0, 9.0, 27.0]
    for share in (0.1, 0.5, 0.95, 0.99, 1.0):
        assert percentile(values, share) in values


# ===== Request summaries =====
def test_summary_counts_failures_and_error_rate():
    summary = summarize_requests([request(), request(failed=True), request(), request()])
    assert (summary.requests, summary.failures, summary.error_rate) == (4, 1, 0.25)


def test_summary_of_no_requests_reports_nothing_instead_of_zero():
    summary = summarize_requests([])
    assert summary.requests == 0
    assert summary.error_rate is None
    assert summary.p50_ms is None and summary.p95_ms is None and summary.max_ms is None


def test_summary_latency_includes_failed_requests():
    summary = summarize_requests([request(ms=5), request(ms=5000, failed=True)])
    assert summary.max_ms == 5000


# ===== Server counters =====
def test_counter_reading_uses_the_latest_sample_before_the_moment():
    samples = [sample(START, 10), sample(START + 1, 15), sample(START + 2, 30)]
    assert counter_at(samples, START + 1.5) == 15
    assert counter_at(samples, START - 1) is None
    assert counter_delta(samples, START, START + 2) == 20
    assert counter_delta(samples, START - 5, START + 2) is None


# ===== Full result =====
def test_result_totals_rates_and_endpoints():
    records = [request("/feed", ms=10), request("/feed", ms=20), request("/stats", ms=900, failed=True)]
    run = result(records, samples=[sample(START - 1, 100), sample(START + 4, 106)])
    assert run.overall.requests == 3
    assert run.overall.error_rate == round(1 / 3, 4)
    assert run.request_rate_per_second == 1.0
    assert set(run.endpoints) == {"/feed", "/stats"}
    assert run.endpoints["/stats"].failures == 1
    assert run.database.queries == 6
    assert run.database.queries_per_request == 2.0


def test_requests_are_grouped_by_the_second_they_finished():
    records = [request(end=START + 0.2), request(end=START + 0.9), request(end=START + 2.5, ms=50)]
    rows = result(records).seconds
    assert [row.requests for row in rows] == [2, 0, 1]
    assert rows[1].p95_ms is None
    assert rows[2].p95_ms == 50


def test_a_skipped_tick_loses_no_requests():
    # Ticks drift, so second 1 can be skipped: the tick after second 0 reports second 2.
    drifted = [
        {"second": 0, "time": START, "target": 5, "actual": 5},
        {"second": 2, "time": START + 1.012, "target": 5, "actual": 5},
        {"second": 3, "time": START + 2.02, "target": 5, "actual": 5},
    ]
    records = [request(end=START + 0.5), request(end=START + 1.0), request(end=START + 1.5), request(end=START + 2.9)]
    run = build_result(
        run_id="run_test", created_at="x", settings={}, environment={}, records=records,
        trace=drifted, samples=[], follows_timeline=True,
    )
    assert [row.second for row in run.seconds] == [0, 2, 3]
    assert [row.requests for row in run.seconds] == [2, 1, 1]
    assert sum(row.requests for row in run.seconds) == run.overall.requests
    assert run.duration_seconds == 3


def test_requests_outside_the_replay_count_in_totals_only():
    records = [request(end=START - 0.5), request(end=START + 0.5), request(end=START + 3.5)]
    run = result(records)
    assert run.overall.requests == 3
    assert sum(row.requests for row in run.seconds) == 1


def test_per_second_database_queries_come_from_counter_readings():
    samples = [sample(START, 0), sample(START + 1, 4), sample(START + 2, 4), sample(START + 3, 9)]
    rows = result(samples=samples).seconds
    assert [row.db_queries for row in rows] == [4, 0, 5]


def test_cache_hit_rate_is_not_measured_when_cache_is_off():
    run = result(samples=[sample(START, 0), sample(START + 3, 1)])
    assert run.cache.enabled is False
    assert run.cache.hit_rate is None


def test_cache_hit_rate_is_calculated_when_cache_is_on():
    run = result(samples=[sample(START, 0, True, 0, 0), sample(START + 3, 1, True, 3, 1)])
    assert run.cache.hit_rate == 0.75


def test_missing_counter_readings_are_not_filled_in():
    run = result([request()], samples=[])
    assert run.database.queries is None
    assert run.database.queries_per_request is None
    assert all(row.db_queries is None for row in run.seconds)


def test_result_needs_a_trace():
    with pytest.raises(ValueError, match="trace"):
        build_result(
            run_id="x", created_at="x", settings={}, environment={}, records=[], trace=[], samples=[],
            follows_timeline=False,
        )


def test_result_states_that_traffic_is_simulated():
    assert "simulated" in result().disclaimer


def test_saved_result_reads_back_identically():
    run = result([request(), request(failed=True)], samples=[sample(START, 0), sample(START + 3, 4)])
    text = serialize(run.model_dump())
    assert RunResult.model_validate_json(text) == run
    assert serialize(RunResult.model_validate_json(text).model_dump()) == text


def test_result_format_rejects_unknown_fields():
    data = result().model_dump()
    data["invented_metric"] = 1
    with pytest.raises(ValidationError):
        RunResult.model_validate(data)
