"""Run a replay against the local API and save its result. Run with: python -m scripts.run_replay --short

Traffic is simulated. StatsBomb provides match events, not platform traffic.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from app.timeline import serialize
from loadgen.results import RunResult, build_result
from loadgen.safety import require_local_target
from loadgen.schedule import (
    BASE_USERS_VARIABLE,
    DEFAULT_BASE_USERS,
    REPLAY_SECONDS_VARIABLE,
    REQUESTS_PATH_VARIABLE,
    SHORT_REPLAY_SECONDS,
    TRACE_PATH_VARIABLE,
    ReplayPlan,
    build_plan,
    summarize_trace,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCUSTFILE = PROJECT_ROOT / "loadgen" / "locustfile.py"
RAW_FOLDER = PROJECT_ROOT / "results" / "raw"
RUNS_FOLDER = PROJECT_ROOT / "results" / "runs"
DEFAULT_HOST = "http://127.0.0.1:8000"
CHECK_TIMEOUT_SECONDS = 5
SAMPLE_EVERY_SECONDS = 0.5
# Longer than the fans' 10-second request timeout, so in-flight requests finish or fail visibly.
STOP_TIMEOUT_SECONDS = 12
RECOVERY_LIMIT_SECONDS = 180
RECOVERY_CHECK_TIMEOUT_SECONDS = 2
PROTECTION_NAMES = ("cache", "stampede_lock", "rate_limit", "load_shedding")
REQUEST_MIX = {"/matches/[id]/feed": 7, "/matches/[id]": 2, "/matches/[id]/stats": 1}


# ===== HTTP helpers =====
def open_url(url: str, timeout: float = CHECK_TIMEOUT_SECONDS):
    """Open a URL without any proxy, so local requests stay local."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)


def http_status(url: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> int | None:
    """Return a URL's HTTP status, or None if nothing answered in time."""
    try:
        with open_url(url, timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return None


def read_server_metrics(host: str) -> dict | None:
    """Read the API's counters, or None if they could not be read."""
    try:
        with open_url(f"{host}/internal/metrics") as response:
            return json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ===== Recovery =====
def wait_until_healthy(host: str, limit_seconds: float = RECOVERY_LIMIT_SECONDS) -> float | None:
    """Return seconds until /health answers 200 quickly, or None if it did not within the limit."""
    started = time.monotonic()
    while time.monotonic() - started < limit_seconds:
        if http_status(f"{host}/health", RECOVERY_CHECK_TIMEOUT_SECONDS) == 200:
            return round(time.monotonic() - started, 1)
        time.sleep(0.5)
    return None


# ===== Pre-flight =====
def preflight_problem(host: str, plan: ReplayPlan) -> str | None:
    """Describe why a replay cannot start yet, or return None if the API is ready."""
    health = http_status(f"{host}/health")
    if health != 200:
        return (
            f"The API is not ready at {host} (health check: {health}). "
            "Start it with: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        )
    match = http_status(f"{host}/matches/{plan.match_id}")
    if match != 200:
        return f"Match {plan.match_id} is not loaded (status: {match}). Run: python -m scripts.seed"
    if read_server_metrics(host) is None:
        return "The API's /internal/metrics endpoint is missing. Restart the API so it runs the latest code."
    return None


# ===== Server counter sampling =====
class CounterSampler:
    """Read the API's counters in the background while a replay runs."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _take(self) -> None:
        """Record one reading with the time it was taken."""
        reading = read_server_metrics(self.host)
        if reading is not None:
            self.samples.append({"time": time.time(), **reading})

    def _run(self) -> None:
        """Take readings until asked to stop."""
        while not self._stop.is_set():
            self._take()
            self._stop.wait(SAMPLE_EVERY_SECONDS)

    def __enter__(self) -> "CounterSampler":
        self._take()
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        self._thread.join()
        self._take()


def protections_from(samples: list[dict]) -> dict:
    """Return the protections the API itself reported. A protection it did not report is None, not False."""
    reported = samples[0].get("protections", {}) if samples else {}
    return {name: reported.get(name) for name in PROTECTION_NAMES}


# ===== Replay =====
def run_locust(host: str, plan: ReplayPlan, trace_path: Path, requests_path: Path) -> int:
    """Run Locust to the end of the replay, and return its exit code."""
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        REPLAY_SECONDS_VARIABLE: str(len(plan.targets)),
        BASE_USERS_VARIABLE: str(plan.base_users),
        TRACE_PATH_VARIABLE: str(trace_path),
        REQUESTS_PATH_VARIABLE: str(requests_path),
    }
    command = [
        sys.executable, "-m", "locust",
        "-f", str(LOCUSTFILE),
        "--headless",
        "--host", host,
        "--only-summary",
        "--loglevel", "WARNING",
        "--stop-timeout", str(STOP_TIMEOUT_SECONDS),
    ]
    return subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode


# ===== Result =====
def git_state() -> dict:
    """Return the current commit and whether there are uncommitted changes."""
    def git(*arguments: str) -> str:
        result = subprocess.run(["git", *arguments], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip()

    return {"commit": git("rev-parse", "--short", "HEAD") or None, "uncommitted_changes": bool(git("status", "--porcelain"))}


def describe_environment() -> dict:
    """Describe the machine and software, so results can be compared fairly."""
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "locust": version("locust"),
        "git": git_state(),
        "load_generator_on_same_machine": True,
    }


def save_result(
    run_id: str,
    created_at: str,
    host: str,
    plan: ReplayPlan,
    raw_folder: Path,
    samples: list[dict],
    recovery_seconds: float | None = None,
) -> RunResult:
    """Build the result from the raw files and write it to the runs folder."""
    trace = json.loads((raw_folder / "trace.json").read_text(encoding="utf-8"))
    requests_file = raw_folder / "requests.jsonl"
    records = [json.loads(line) for line in requests_file.read_text(encoding="utf-8").splitlines() if line]
    result = build_result(
        run_id=run_id,
        created_at=created_at,
        settings={
            "replay_seconds": len(plan.targets),
            "base_users": plan.base_users,
            "peak_users": plan.peak_users,
            "host": host,
            "match_id": plan.match_id,
            "timeline_fingerprint": plan.timeline_fingerprint,
            "protections": protections_from(samples),
            "request_mix": REQUEST_MIX,
        },
        environment=describe_environment(),
        records=records,
        trace=trace,
        samples=samples,
        follows_timeline=summarize_trace(trace)["follows_timeline"],
    )
    result = result.model_copy(
        update={"recovery_seconds": recovery_seconds, "recovery_limit_seconds": RECOVERY_LIMIT_SECONDS}
    )
    RunResult.model_validate(result.model_dump())
    RUNS_FOLDER.mkdir(parents=True, exist_ok=True)
    (RUNS_FOLDER / f"{run_id}.json").write_text(serialize(result.model_dump()), encoding="utf-8", newline="\n")
    return result


def print_result(result: RunResult) -> None:
    """Print the headline numbers from a saved result."""
    overall = result.overall

    def number(value, suffix: str = "") -> str:
        return "not measured" if value is None else f"{value}{suffix}"

    error_rate = "n/a" if overall.error_rate is None else f"{overall.error_rate:.2%}"
    print("Result (measured from this run):")
    print(f"  requests: {overall.requests}, failures: {overall.failures} ({error_rate})")
    print(f"  request rate: {result.request_rate_per_second} per second")
    print(f"  latency: p50 {number(overall.p50_ms, ' ms')}, p95 {number(overall.p95_ms, ' ms')}")
    print(f"  database queries: {number(result.database.queries)} ({number(result.database.queries_per_request)} per request)")
    print(
        f"  cache hit rate: {number(result.cache.hit_rate)} (cache enabled: {result.cache.enabled}, "
        f"Redis errors: {number(result.cache.errors)})"
    )
    if result.pool is not None:
        print(
            f"  connection pool: up to {result.pool.waiting_max} requests waiting, "
            f"{result.pool.failed_requests} could not get a connection"
        )
    recovery = (
        f"{result.recovery_seconds} s" if result.recovery_seconds is not None
        else f"not within {result.recovery_limit_seconds} s"
    )
    print(f"  recovery after the replay: {recovery}")
    print(f"  followed the timeline: {result.follows_timeline}")
    print(f"  saved: {RUNS_FOLDER / (result.run_id + '.json')}")


# ===== Command line =====
def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line options."""
    parser = argparse.ArgumentParser(description="Replay the match as simulated local traffic.")
    length = parser.add_mutually_exclusive_group()
    length.add_argument("--short", action="store_true", help=f"run for {SHORT_REPLAY_SECONDS} seconds")
    length.add_argument("--replay-seconds", type=int, help="run for this many seconds")
    parser.add_argument("--base-users", type=int, default=DEFAULT_BASE_USERS)
    parser.add_argument("--host", default=DEFAULT_HOST, help="local API address only")
    return parser.parse_args(argv)


def new_run_id(now: datetime) -> str:
    """Return a run ID from the time, adding a suffix if that ID is already taken."""
    base = now.strftime("run_%Y%m%dT%H%M%SZ")
    run_id, suffix = base, 1
    while (RAW_FOLDER / run_id).exists() or (RUNS_FOLDER / f"{run_id}.json").exists():
        suffix += 1
        run_id = f"{base}_{suffix}"
    return run_id


def execute_replay(host: str, plan: ReplayPlan) -> tuple[int, RunResult | None]:
    """Run one checked replay, save its result, and return Locust's exit code and the result."""
    now = datetime.now(timezone.utc)
    run_id = new_run_id(now)
    raw_folder = RAW_FOLDER / run_id
    raw_folder.mkdir(parents=True)

    print("Traffic is simulated. StatsBomb provides match events, not platform traffic.")
    print(
        f"Replay: {len(plan.targets)} seconds, {plan.base_users} base users, "
        f"peak {plan.peak_users} users, target {host}",
        flush=True,
    )
    metrics = read_server_metrics(host) or {}
    active = [name for name, on in metrics.get("protections", {}).items() if on]
    print(f"Protections reported by the API: {', '.join(active) or 'none'}", flush=True)

    with CounterSampler(host) as sampler:
        locust_code = run_locust(host, plan, raw_folder / "trace.json", raw_folder / "requests.jsonl")
        recovery_seconds = wait_until_healthy(host)

    try:
        result = save_result(
            run_id, now.isoformat(timespec="seconds"), host, plan, raw_folder, sampler.samples, recovery_seconds
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"The run finished but its result could not be built: {error}")
        return locust_code, None

    print_result(result)
    return locust_code, result


def main(argv: list[str] | None = None) -> int:
    """Check the target, API and settings, run the replay, then save and report the result."""
    arguments = parse_arguments(argv)
    try:
        host = require_local_target(arguments.host)
        seconds = SHORT_REPLAY_SECONDS if arguments.short else arguments.replay_seconds
        plan = build_plan(seconds, arguments.base_users)
    except ValueError as error:
        print(f"Refused: {error}")
        return 2

    problem = preflight_problem(host, plan)
    if problem:
        print(problem)
        return 2

    locust_code, result = execute_replay(host, plan)
    if result is None:
        return 1
    if locust_code != 0:
        print(f"Locust exited with code {locust_code}. Code 1 means some requests failed.")
        return locust_code
    return 0 if result.follows_timeline else 1


if __name__ == "__main__":
    sys.exit(main())
