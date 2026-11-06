"""Run a replay against the local API. Run with: python -m scripts.run_replay --short

Traffic is simulated. StatsBomb provides match events, not platform traffic.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from loadgen.safety import UnsafeTargetError, require_local_target
from loadgen.schedule import (
    BASE_USERS_VARIABLE,
    DEFAULT_BASE_USERS,
    REPLAY_SECONDS_VARIABLE,
    SHORT_REPLAY_SECONDS,
    TRACE_PATH_VARIABLE,
    ReplayPlan,
    build_plan,
    summarize_trace,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCUSTFILE = PROJECT_ROOT / "loadgen" / "locustfile.py"
TRACE_FOLDER = PROJECT_ROOT / "results" / "raw"
DEFAULT_HOST = "http://127.0.0.1:8000"
CHECK_TIMEOUT_SECONDS = 5


# ===== Pre-flight =====
def http_status(url: str) -> int | None:
    """Return a URL's HTTP status, or None if nothing answered. Proxies are never used."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=CHECK_TIMEOUT_SECONDS) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return None


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
    return None


# ===== Replay =====
def run_locust(host: str, plan: ReplayPlan, trace_path: Path) -> int:
    """Run Locust to the end of the replay, and return its exit code."""
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        REPLAY_SECONDS_VARIABLE: str(len(plan.targets)),
        BASE_USERS_VARIABLE: str(plan.base_users),
        TRACE_PATH_VARIABLE: str(trace_path),
    }
    command = [
        sys.executable, "-m", "locust",
        "-f", str(LOCUSTFILE),
        "--headless",
        "--host", host,
        "--only-summary",
        "--loglevel", "WARNING",
    ]
    return subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode


def report_trace(trace_path: Path) -> bool:
    """Print how closely the real user count followed the plan, and return whether it did."""
    if not trace_path.exists():
        print("No user record was saved, so following the timeline could not be checked.")
        return False
    summary = summarize_trace(json.loads(trace_path.read_text(encoding="utf-8")))
    print(
        f"Followed the timeline: {summary['follows_timeline']} "
        f"({summary['share_on_target']:.1%} of {summary['seconds']} seconds on target, "
        f"largest gap {summary['largest_gap']} users, peak {summary['peak_actual']} users)"
    )
    print(f"User record: {trace_path}")
    return summary["follows_timeline"]


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


def main(argv: list[str] | None = None) -> int:
    """Check the target, API and settings, run the replay, and report the result."""
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

    print("Traffic is simulated. StatsBomb provides match events, not platform traffic.")
    print(
        f"Replay: {len(plan.targets)} seconds, {plan.base_users} base users, "
        f"peak {plan.peak_users} users, target {host}",
        flush=True,
    )

    TRACE_FOLDER.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trace_path = TRACE_FOLDER / f"user_trace_{stamp}.json"

    locust_code = run_locust(host, plan, trace_path)
    followed = report_trace(trace_path)
    if locust_code != 0:
        print(f"Locust exited with code {locust_code}. Code 1 means some requests failed; see the summary above.")
        return locust_code
    return 0 if followed else 1


if __name__ == "__main__":
    sys.exit(main())
