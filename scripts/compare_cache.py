"""Compare the same full replay with the cache off and on.

  python -m scripts.compare_cache --base-users 15 --repeats 3

This script starts and stops the API itself, so each run uses exactly the setting it
claims. Stop your own API first. Runs alternate off, on, off, on..., so any slow drift
on this computer affects both settings alike. The cache is emptied before every run.

Traffic is simulated. StatsBomb provides match events, not platform traffic.
Results only describe the machine they were measured on.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.cache import ResponseCache, create_client
from app.config import Settings
from loadgen.degradation import REQUIRED_REPEATS, evaluate, summarize_repeats
from loadgen.safety import require_local_target
from loadgen.schedule import SHORT_REPLAY_SECONDS, build_plan
from scripts import run_replay
from scripts.failure_baseline import COOLDOWN_SECONDS, CRITERIA, print_table, write_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FOLDER = PROJECT_ROOT / "results" / "cache"
BASELINE_FILE = PROJECT_ROOT / "results" / "baseline" / "failure_baseline.json"
API_START_LIMIT_SECONDS = 30
API_STOP_LIMIT_SECONDS = 10
MODES = {"off": "false", "on": "true"}
DEFAULT_PORT = 8000


# ===== Managed API =====
class ManagedApi:
    """Run the API on 127.0.0.1 in a child process with one cache setting, and check it reports that setting."""

    def __init__(self, port: int, cache_on: bool, log_path: Path) -> None:
        self.port = port
        self.host = f"http://127.0.0.1:{port}"
        self.cache_on = cache_on
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self._log = None

    def __enter__(self) -> "ManagedApi":
        if run_replay.http_status(f"{self.host}/health") is not None:
            raise RuntimeError(f"Something is already answering at {self.host}. Stop your own API first.")
        env = {**os.environ, "CACHE_ENABLED": MODES["on" if self.cache_on else "off"]}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self.log_path, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=PROJECT_ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT,
        )
        if run_replay.wait_until_healthy(self.host, API_START_LIMIT_SECONDS) is None:
            self.__exit__()
            raise RuntimeError(f"The API did not start. See {self.log_path}")
        reported = (run_replay.read_server_metrics(self.host) or {}).get("protections", {}).get("cache")
        if reported is not self.cache_on:
            self.__exit__()
            raise RuntimeError(f"Asked for cache {self.cache_on}, but the API reports {reported}.")
        return self

    def __exit__(self, *_) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(API_STOP_LIMIT_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        if self._log is not None:
            self._log.close()
            self._log = None


def empty_cache() -> int:
    """Remove every cached response, so each cache-on run starts cold."""
    settings = Settings()
    cache = ResponseCache(create_client(settings), settings.cache_prefix)
    try:
        return cache.clear()
    finally:
        cache.close()


# ===== Comparison =====
def run_order(repeats: int) -> list[str]:
    """Alternate the two settings: off, on, off, on..."""
    return [mode for _ in range(repeats) for mode in ("off", "on")]


def compare(summary_off: dict, summary_on: dict) -> dict:
    """Return the change in key averages from cache off to cache on."""
    changes = {}
    for key in ("feed_p95_ms", "overall_p95_ms", "stats_p95_ms", "error_rate", "request_rate_per_second",
                "db_queries_per_request", "pool_waiting_max"):
        off, on = summary_off[key]["mean"], summary_on[key]["mean"]
        changes[key] = {
            "off": off,
            "on": on,
            "ratio_on_to_off": round(on / off, 4) if off and on is not None else None,
        }
    return changes


def run_comparison(port: int, base_users: int, repeats: int, replay_seconds: int | None) -> int:
    """Run the alternating replays, keep their files, and save the comparison."""
    host = require_local_target(f"http://127.0.0.1:{port}")
    evaluations: dict[str, list[dict]] = {"off": [], "on": []}
    kept_runs = CACHE_FOLDER / "runs"
    order = run_order(repeats)
    for index, mode in enumerate(order):
        if index:
            time.sleep(COOLDOWN_SECONDS)
        print(f"--- Run {index + 1} of {len(order)}: cache {mode} ---")
        print(f"Emptied the cache: {empty_cache()} entries removed")
        plan = build_plan(replay_seconds, base_users)
        log_path = run_replay.RAW_FOLDER / f"api_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{mode}.log"
        try:
            with ManagedApi(port, mode == "on", log_path):
                problem = run_replay.preflight_problem(host, plan)
                if problem:
                    print(problem)
                    return 2
                _, result = run_replay.execute_replay(host, plan)
        except RuntimeError as error:
            print(error)
            return 2
        if result is None:
            return 2
        evaluation = {**evaluate(result), "cache": mode}
        evaluations[mode].append(evaluation)
        if replay_seconds is None:
            kept_runs.mkdir(parents=True, exist_ok=True)
            source = run_replay.RUNS_FOLDER / f"{result.run_id}.json"
            shutil.copyfile(source, kept_runs / source.name)
        verdict = "DEGRADED" if evaluation["degraded"] else "healthy"
        print(f"=> cache {mode}: {verdict}; {', '.join(evaluation['reasons']) or 'within thresholds'}\n")

    for mode in ("off", "on"):
        print(f"Cache {mode}:")
        print_table(evaluations[mode])
    summaries = {mode: summarize_repeats(evaluations[mode]) for mode in ("off", "on")}
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8")) if BASELINE_FILE.exists() else None

    output = {
        "disclaimer": "Traffic is simulated. StatsBomb provides match events, not platform traffic. "
        "Measured on one machine, with the load generator on the same computer.",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "criteria": CRITERIA,
        "settings": {
            "base_users": base_users,
            "replay_seconds": replay_seconds or len(build_plan(None, base_users).targets),
            "repeats_per_setting": repeats,
            "order": order,
            "cache_ttl_seconds": cache_ttls(),
        },
        "runs": evaluations,
        "summary": summaries,
        "change_off_to_on": compare(summaries["off"], summaries["on"]),
        "stage6_baseline_summary": baseline["summary"] if baseline else None,
    }
    name = "comparison.json" if replay_seconds is None else f"comparison_{replay_seconds}s.json"
    write_json(CACHE_FOLDER / name, output)
    for mode in ("off", "on"):
        s = summaries[mode]
        print(
            f"Cache {mode}: {s['degraded_runs']} of {s['runs']} runs degraded; mean feed p95 "
            f"{s['feed_p95_ms']['mean']} ms, mean error rate {s['error_rate']['mean']}"
        )
    print(f"Saved: {CACHE_FOLDER / name}")
    return 0


def cache_ttls() -> dict:
    """Return the TTLs the API will use, from the same settings it reads."""
    settings = Settings()
    return {
        "match": settings.cache_ttl_match_seconds,
        "feed": settings.cache_ttl_feed_seconds,
        "stats": settings.cache_ttl_stats_seconds,
    }


# ===== Command line =====
def main(argv: list[str] | None = None) -> int:
    """Check the options, then run the comparison."""
    parser = argparse.ArgumentParser(description="Compare the same replay with the cache off and on.")
    parser.add_argument("--base-users", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=REQUIRED_REPEATS)
    parser.add_argument("--short", action="store_true", help=f"{SHORT_REPLAY_SECONDS}-second replays, not kept")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="the API always runs on 127.0.0.1")
    arguments = parser.parse_args(argv)
    try:
        if not 1024 <= arguments.port <= 65535:
            raise ValueError("The port must be 1024 to 65535.")
        build_plan(SHORT_REPLAY_SECONDS, arguments.base_users)
        if not 1 <= arguments.repeats <= 10:
            raise ValueError("Repeats must be 1 to 10.")
    except ValueError as error:
        print(f"Refused: {error}")
        return 2
    return run_comparison(arguments.port, arguments.base_users, arguments.repeats,
                          SHORT_REPLAY_SECONDS if arguments.short else None)


if __name__ == "__main__":
    sys.exit(main())
