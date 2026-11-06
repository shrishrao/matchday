"""Tests for the replay plan, the run command's checks, and a real short replay."""

import json
import threading
import time

import pytest
import uvicorn

from app.main import create_app
from app.timeline import TIMELINE_PATH, load_profile
from loadgen.schedule import (
    BASE_USERS_VARIABLE,
    MAX_BASE_USERS,
    REPLAY_SECONDS_VARIABLE,
    SHORT_REPLAY_SECONDS,
    build_plan,
    plan_from_environment,
    scale_profile,
    summarize_trace,
    users_for,
)
from scripts import run_replay

LIVE_TEST_PORT = 8765


# ===== User counts =====
@pytest.mark.parametrize(
    ("multiplier", "base", "expected"),
    [(1.0, 5, 5), (8.0, 5, 40), (2.2, 5, 11), (0.01, 5, 1), (8.0, 500, 4000)],
)
def test_users_for_multiplier(multiplier, base, expected):
    assert users_for(multiplier, base) == expected


def test_full_plan_follows_the_committed_timeline():
    timeline = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))
    plan = build_plan(base_users=5)
    expected = tuple(users_for(point["multiplier"], 5) for point in timeline["points"])
    assert plan.targets == expected
    assert len(plan.targets) == 180
    assert plan.match_id == timeline["match_id"]


def test_same_settings_give_the_same_plan():
    assert build_plan(30, 5) == build_plan(30, 5)


def test_more_base_users_scale_the_plan():
    assert build_plan(base_users=10).peak_users > build_plan(base_users=5).peak_users


def test_target_ends_when_the_replay_ends():
    plan = build_plan(SHORT_REPLAY_SECONDS, 5)
    assert plan.target_at(0) == plan.targets[0]
    assert plan.target_at(29.9) == plan.targets[29]
    assert plan.target_at(30) is None


def test_spawn_rate_can_reach_the_peak_within_a_second():
    plan = build_plan(base_users=5)
    assert plan.spawn_rate == plan.peak_users


# ===== Short replay =====
def test_short_replay_keeps_the_match_shape():
    plan = build_plan(SHORT_REPLAY_SECONDS, 5)
    assert len(plan.targets) == SHORT_REPLAY_SECONDS
    assert plan.targets[0] == 5
    assert plan.peak_users > plan.targets[0]
    assert min(plan.targets) == 5
    assert len(plan.moments) == 19


def test_scaling_shrinks_spikes_with_the_replay():
    profile = load_profile()
    scaled = scale_profile(profile, 30)
    assert scaled.replay_seconds == 30
    assert scaled.spikes.goal.duration_seconds == 2
    assert scaled.spikes.shootout_kick.duration_seconds == 1


def test_scaling_to_the_same_length_changes_nothing():
    profile = load_profile()
    assert scale_profile(profile, profile.replay_seconds) == profile


# ===== Settings =====
@pytest.mark.parametrize(
    "settings",
    [
        {"replay_seconds": 9},
        {"replay_seconds": 3601},
        {"base_users": 0},
        {"base_users": MAX_BASE_USERS + 1},
    ],
)
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        build_plan(**{"replay_seconds": 30, "base_users": 5, **settings})


def test_plan_reads_the_environment():
    plan = plan_from_environment({REPLAY_SECONDS_VARIABLE: "20", BASE_USERS_VARIABLE: "2"})
    assert len(plan.targets) == 20
    assert plan.base_users == 2


def test_plan_defaults_to_the_full_replay():
    assert len(plan_from_environment({}).targets) == 180


@pytest.mark.parametrize(
    "env", [{BASE_USERS_VARIABLE: "many"}, {BASE_USERS_VARIABLE: "0"}, {REPLAY_SECONDS_VARIABLE: "1"}]
)
def test_plan_rejects_invalid_environment(env):
    with pytest.raises(ValueError):
        plan_from_environment(env)


# ===== Trace comparison =====
def rows(targets, actuals):
    """Build trace rows from matching lists."""
    return [
        {"second": index, "target": target, "actual": actual}
        for index, (target, actual) in enumerate(zip(targets, actuals))
    ]


def test_trace_following_the_plan_passes():
    # Actual users are read one second later than the target they answer.
    summary = summarize_trace(rows([5, 10, 20, 5], [0, 5, 10, 20]))
    assert summary["follows_timeline"] is True
    assert summary["share_on_target"] == 1.0
    assert summary["largest_gap"] == 0


def test_trace_not_following_the_plan_fails():
    summary = summarize_trace(rows([5, 40, 40, 40], [0, 5, 5, 5]))
    assert summary["follows_timeline"] is False
    assert summary["largest_gap"] == 35


@pytest.mark.parametrize("trace", [[], [{"second": 0, "target": 5, "actual": 0}]])
def test_trace_too_short_to_compare_fails(trace):
    assert summarize_trace(trace)["follows_timeline"] is False


# ===== Run command =====
@pytest.fixture
def no_traffic(monkeypatch):
    """Fail the test if the command tries to contact the API or start Locust."""

    def forbidden(*_, **__):
        raise AssertionError("This should not have been reached")

    monkeypatch.setattr(run_replay, "http_status", forbidden)
    monkeypatch.setattr(run_replay, "run_locust", forbidden)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--host", "http://example.com"],
        ["--host", "http://192.168.1.10:8000"],
        ["--base-users", "0"],
        ["--base-users", "100000"],
        ["--replay-seconds", "1"],
    ],
)
def test_run_command_refuses_before_any_traffic(no_traffic, arguments, capsys):
    assert run_replay.main(arguments) == 2
    assert "Refused" in capsys.readouterr().out


def test_run_command_explains_when_the_api_is_down(monkeypatch, capsys):
    monkeypatch.setattr(run_replay, "http_status", lambda _: None)
    monkeypatch.setattr(run_replay, "run_locust", lambda *_: pytest.fail("Locust should not start"))
    assert run_replay.main(["--short"]) == 2
    assert "uvicorn" in capsys.readouterr().out


def test_run_command_explains_when_the_match_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(run_replay, "http_status", lambda url: 200 if url.endswith("/health") else 404)
    monkeypatch.setattr(run_replay, "run_locust", lambda *_: pytest.fail("Locust should not start"))
    assert run_replay.main(["--short"]) == 2
    assert "scripts.seed" in capsys.readouterr().out


def test_http_status_returns_none_when_nothing_answers():
    assert run_replay.http_status("http://127.0.0.1:1/health") is None


# ===== Real replay =====
@pytest.fixture
def live_api(test_settings):
    """Run the API in a background thread, against the test database."""
    config = uvicorn.Config(
        create_app(test_settings), host="127.0.0.1", port=LIVE_TEST_PORT, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.1)
    assert server.started
    yield f"http://127.0.0.1:{LIVE_TEST_PORT}"
    server.should_exit = True
    thread.join(timeout=15)


@pytest.mark.integration
def test_real_replay_sends_requests_and_follows_the_timeline(live_api, tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(run_replay, "TRACE_FOLDER", tmp_path)
    code = run_replay.main(["--replay-seconds", "12", "--base-users", "2", "--host", live_api])
    captured = capfd.readouterr()
    output = captured.out + captured.err

    assert code == 0, output
    assert "Traffic is simulated" in output
    assert "Followed the timeline: True" in output
    assert "/matches/[id]/feed" in output

    trace = json.loads(next(tmp_path.glob("user_trace_*.json")).read_text(encoding="utf-8"))
    plan = build_plan(12, 2)
    assert [row["target"] for row in trace] == list(plan.targets[: len(trace)])
    assert len(trace) >= 11
