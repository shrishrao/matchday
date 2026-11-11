"""Tests for the cache-off versus cache-on comparison command."""

import pytest

from scripts import compare_cache, run_replay

MANAGED_TEST_PORT = 8766


# ===== Order and comparison =====
def test_runs_alternate_between_settings():
    assert compare_cache.run_order(3) == ["off", "on", "off", "on", "off", "on"]


def spread_of(mean):
    """Build a minimal spread with only a mean."""
    return {"mean": mean}


def test_comparison_reports_the_ratio_of_means():
    keys = ("feed_p95_ms", "overall_p95_ms", "stats_p95_ms", "error_rate", "request_rate_per_second",
            "db_queries_per_request", "pool_waiting_max")
    off = {key: spread_of(10.0) for key in keys}
    on = {key: spread_of(2.5) for key in keys}
    on["error_rate"] = spread_of(0.0)
    changes = compare_cache.compare(off, on)
    assert changes["feed_p95_ms"] == {"off": 10.0, "on": 2.5, "ratio_on_to_off": 0.25}
    assert changes["error_rate"]["ratio_on_to_off"] == 0.0


def test_comparison_does_not_divide_by_zero():
    keys = ("feed_p95_ms", "overall_p95_ms", "stats_p95_ms", "error_rate", "request_rate_per_second",
            "db_queries_per_request", "pool_waiting_max")
    off = {key: spread_of(0.0) for key in keys}
    on = {key: spread_of(None) for key in keys}
    assert all(change["ratio_on_to_off"] is None for change in compare_cache.compare(off, on).values())


# ===== Refusals =====
@pytest.fixture
def no_traffic(monkeypatch):
    """Fail the test if the command tries to start the API or a replay."""

    def forbidden(*_, **__):
        raise AssertionError("This should not have been reached")

    monkeypatch.setattr(compare_cache, "run_comparison", forbidden)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--base-users", "0"],
        ["--base-users", "15", "--repeats", "0"],
        ["--base-users", "15", "--repeats", "11"],
        ["--base-users", "15", "--port", "80"],
        ["--base-users", "15", "--port", "70000"],
    ],
)
def test_command_refuses_bad_options_before_any_traffic(no_traffic, arguments, capsys):
    assert compare_cache.main(arguments) == 2
    assert "Refused" in capsys.readouterr().out


def test_managed_api_refuses_when_another_api_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(run_replay, "http_status", lambda *_: 200)
    with pytest.raises(RuntimeError, match="Stop your own API first"):
        with compare_cache.ManagedApi(MANAGED_TEST_PORT, True, tmp_path / "api.log"):
            pass


# ===== Real child process =====
@pytest.mark.integration
@pytest.mark.parametrize("cache_on", [False, True])
def test_managed_api_starts_with_the_asked_for_cache_setting(tmp_path, cache_on):
    with compare_cache.ManagedApi(MANAGED_TEST_PORT, cache_on, tmp_path / "api.log") as api:
        metrics = run_replay.read_server_metrics(api.host)
    assert metrics["protections"]["cache"] is cache_on
    assert run_replay.http_status(f"http://127.0.0.1:{MANAGED_TEST_PORT}/health", 1) is None
