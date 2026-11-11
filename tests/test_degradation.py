"""Tests for the degradation thresholds and the failure baseline command."""

import json

import pytest

from loadgen import degradation
from loadgen.degradation import evaluate, spread, summarize_repeats
from loadgen.results import build_result
from scripts import failure_baseline, run_replay

START = 1_000.0
FEED = "/matches/[id]/feed"


# ===== Helpers =====
def run(feed_ms=10.0, failures=0, total=100, pool=None, base_users=5):
    """Build a result whose feed latency and failure count are set directly."""
    records = [
        {"name": FEED, "end_time": START + 0.5, "response_time_ms": feed_ms, "failed": index < failures}
        for index in range(total)
    ]
    samples = []
    if pool is not None:
        samples = [
            {"time": START, "db_queries_total": 0, "cache": {"enabled": False, "hits": None, "misses": None},
             "pool": {"size": 10, "available": 0, "waiting": pool, "failed_requests": 0}},
            {"time": START + 1, "db_queries_total": 5, "cache": {"enabled": False, "hits": None, "misses": None},
             "pool": {"size": 10, "available": 0, "waiting": 0, "failed_requests": 3}},
        ]
    return build_result(
        run_id=f"run_{base_users}_{feed_ms}_{failures}",
        created_at="x",
        settings={"base_users": base_users, "peak_users": base_users * 8},
        environment={},
        records=records,
        trace=[{"second": 0, "time": START, "target": 5, "actual": 5}],
        samples=samples,
        follows_timeline=True,
    )


def evaluation(degraded, base_users=5, feed=10.0, error_rate=0.0):
    """Build a minimal evaluation."""
    return {
        "run_id": f"run_{base_users}",
        "base_users": base_users,
        "peak_users": base_users * 8,
        "requests": 100,
        "request_rate_per_second": 10.0,
        "feed_p95_ms": feed,
        "overall_p95_ms": feed,
        "error_rate": error_rate,
        "pool_waiting_max": 0,
        "degraded": degraded,
        "reasons": ["x"] if degraded else [],
    }


# ===== Thresholds =====
def test_healthy_run_is_not_degraded():
    assert evaluate(run(feed_ms=10)).get("degraded") is False


@pytest.mark.parametrize("feed_ms", [500.0, 2000.0])
def test_slow_feed_is_degraded(feed_ms):
    result = evaluate(run(feed_ms=feed_ms))
    assert result["degraded"] is True
    assert "feed p95" in result["reasons"][0]


def test_feed_just_under_the_threshold_is_healthy():
    assert evaluate(run(feed_ms=499.9))["degraded"] is False


def test_one_percent_errors_is_degraded():
    result = evaluate(run(failures=1, total=100))
    assert result["degraded"] is True
    assert "error rate" in result["reasons"][0]


def test_under_one_percent_errors_is_healthy():
    assert evaluate(run(failures=1, total=101))["degraded"] is False


def test_both_reasons_are_reported():
    assert len(evaluate(run(feed_ms=900, failures=5))["reasons"]) == 2


def test_pool_pressure_is_reported():
    result = evaluate(run(pool=7))
    assert result["pool_waiting_max"] == 7


def test_thresholds_match_the_recorded_decision():
    assert degradation.FEED_P95_DEGRADED_MS == 500.0
    assert degradation.ERROR_RATE_DEGRADED == 0.01
    assert degradation.REQUIRED_REPEATS == 3


# ===== Repeats =====
def test_spread_of_values():
    assert spread([1.0, 2.0, 3.0]) == {"mean": 2.0, "min": 1.0, "max": 3.0, "stdev": 1.0, "runs": 3}
    assert spread([None, None])["mean"] is None
    assert spread([5.0])["stdev"] is None


def test_three_degraded_runs_are_repeatable():
    assert summarize_repeats([evaluation(True)] * 3)["repeatable"] is True


@pytest.mark.parametrize("runs", [[True, True, False], [True, True]])
def test_a_healthy_run_or_too_few_runs_is_not_repeatable(runs):
    assert summarize_repeats([evaluation(d) for d in runs])["repeatable"] is False


# ===== Command =====
@pytest.fixture
def fake_runs(monkeypatch, tmp_path):
    """Replace real replays with results whose feed latency depends on the load."""
    monkeypatch.setattr(failure_baseline, "BASELINE_FOLDER", tmp_path / "baseline")
    monkeypatch.setattr(failure_baseline, "COOLDOWN_SECONDS", 0)
    monkeypatch.setattr(run_replay, "RUNS_FOLDER", tmp_path / "runs")
    monkeypatch.setattr(run_replay, "preflight_problem", lambda *_: None)
    monkeypatch.setattr(run_replay, "wait_until_healthy", lambda *_: 0.0)

    def fake_execute(host, plan):
        result = run(feed_ms=20.0 * plan.base_users, base_users=plan.base_users)
        result = result.model_copy(update={"settings": {**result.settings, "replay_seconds": len(plan.targets),
                                                        "timeline_fingerprint": "f", "protections": {}}})
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / f"{result.run_id}.json").write_text(result.model_dump_json(), encoding="utf-8")
        return 0, result

    monkeypatch.setattr(run_replay, "execute_replay", fake_execute)
    return tmp_path


def test_sweep_reports_the_lowest_degraded_level(fake_runs):
    assert failure_baseline.main(["sweep", "--base-users", "40", "10", "30"]) == 0
    saved = json.loads((fake_runs / "baseline" / "sweep.json").read_text(encoding="utf-8"))
    assert [r["base_users"] for r in saved["runs"]] == [10, 30, 40]
    assert saved["lowest_degraded_base_users"] == 30
    assert saved["criteria"]["fixed_before_tuning"] is True


def test_confirm_keeps_runs_and_reports_repeatable(fake_runs):
    assert failure_baseline.main(["confirm", "--base-users", "30"]) == 0
    saved = json.loads((fake_runs / "baseline" / "failure_baseline.json").read_text(encoding="utf-8"))
    assert saved["summary"]["repeatable"] is True
    assert len(list((fake_runs / "baseline" / "runs").glob("*.json"))) >= 1
    assert "simulated" in saved["disclaimer"]


def test_confirm_at_a_healthy_level_is_not_repeatable(fake_runs):
    assert failure_baseline.main(["confirm", "--base-users", "5"]) == 1


def test_run_stops_if_the_api_never_recovers(fake_runs, monkeypatch, capsys):
    monkeypatch.setattr(run_replay, "wait_until_healthy", lambda *_: None)
    assert failure_baseline.main(["sweep", "--base-users", "10"]) == 2
    assert "did not become healthy" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["sweep", "--base-users", "0"],
        ["sweep", "--base-users", "10", "--host", "http://example.com"],
        ["confirm", "--base-users", "100000"],
        ["confirm", "--base-users", "10", "--repeats", "0"],
    ],
)
def test_invalid_options_are_refused(fake_runs, arguments, capsys):
    assert failure_baseline.main(arguments) == 2
    assert "Refused" in capsys.readouterr().out


# ===== Results folder =====
@pytest.mark.parametrize("name", ["../outside", "a/b", "a\b", "", "x" * 41, "results:1"])
def test_results_folder_refuses_unsafe_names(name):
    with pytest.raises(ValueError):
        failure_baseline.results_folder(name)


def test_results_folder_stays_under_results():
    folder = failure_baseline.results_folder("baseline_v2")
    assert folder.parent == failure_baseline.BASELINE_FOLDER.parent
    assert folder.name == "baseline_v2"


def test_baseline_command_refuses_unsafe_folder(capsys):
    assert failure_baseline.main(["sweep", "--base-users", "5", "--folder", "../x"]) == 2
    assert "Refused" in capsys.readouterr().out
