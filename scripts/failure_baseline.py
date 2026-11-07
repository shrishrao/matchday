"""Find and confirm the load at which the unprotected system degrades on this machine.

  python -m scripts.failure_baseline sweep --base-users 10 20 40 80
  python -m scripts.failure_baseline confirm --base-users 40

Traffic is simulated. StatsBomb provides match events, not platform traffic.
Results only describe the machine they were measured on.
"""

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.timeline import serialize
from loadgen.degradation import (
    ERROR_RATE_DEGRADED,
    FEED_P95_DEGRADED_MS,
    REQUIRED_REPEATS,
    evaluate,
    summarize_repeats,
)
from loadgen.safety import require_local_target
from loadgen.schedule import SHORT_REPLAY_SECONDS, build_plan
from scripts import run_replay

BASELINE_FOLDER = Path(__file__).resolve().parent.parent / "results" / "baseline"
COOLDOWN_SECONDS = 10
CRITERIA = {
    "feed_p95_ms_at_least": FEED_P95_DEGRADED_MS,
    "or_error_rate_at_least": ERROR_RATE_DEGRADED,
    "repeats_required": REQUIRED_REPEATS,
    "fixed_before_tuning": True,
}


# ===== Running =====
def run_once(host: str, replay_seconds: int | None, base_users: int) -> dict | None:
    """Wait for the API to recover, run one replay, and return its evaluation, or None on failure."""
    plan = build_plan(replay_seconds, base_users)
    if run_replay.wait_until_healthy(host) is None:
        print(f"The API did not become healthy within {run_replay.RECOVERY_LIMIT_SECONDS} s.")
        return None
    problem = run_replay.preflight_problem(host, plan)
    if problem:
        print(problem)
        return None
    _, result = run_replay.execute_replay(host, plan)
    if result is None:
        return None
    evaluation = evaluate(result)
    verdict = "DEGRADED" if evaluation["degraded"] else "healthy"
    print(f"=> {verdict} at {base_users} base users: {', '.join(evaluation['reasons']) or 'within thresholds'}\n")
    return evaluation


def print_table(evaluations: list[dict]) -> None:
    """Print one line per run."""
    print("base users | peak users | requests/s | feed p95 ms | error rate | pool waiting max | recovery s | degraded")
    for e in evaluations:
        error_rate = "n/a" if e["error_rate"] is None else f"{e['error_rate']:.2%}"
        print(
            f"{e['base_users']:>10} | {e['peak_users']:>10} | {e['request_rate_per_second']:>10} | "
            f"{e['feed_p95_ms']!s:>11} | {error_rate:>10} | {e['pool_waiting_max']!s:>16} | "
            f"{e.get('recovery_seconds')!s:>10} | {e['degraded']}"
        )


def write_json(path: Path, data: dict) -> None:
    """Write a result file in the project's fixed JSON format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(data), encoding="utf-8", newline="\n")


# ===== Commands =====
def sweep(host: str, levels: list[int]) -> int:
    """Run a short replay at each load level and report the lowest one that degraded."""
    evaluations = []
    for index, base_users in enumerate(levels):
        if index:
            time.sleep(COOLDOWN_SECONDS)
        evaluation = run_once(host, SHORT_REPLAY_SECONDS, base_users)
        if evaluation is None:
            return 2
        evaluations.append(evaluation)

    print_table(evaluations)
    degraded = [e["base_users"] for e in evaluations if e["degraded"]]
    write_json(
        BASELINE_FOLDER / "sweep.json",
        {
            "disclaimer": "Traffic is simulated. Short replays used to choose a load level; measured on one machine.",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "criteria": CRITERIA,
            "replay_seconds": SHORT_REPLAY_SECONDS,
            "runs": evaluations,
            "lowest_degraded_base_users": min(degraded) if degraded else None,
        },
    )
    print(f"Lowest degraded level: {min(degraded) if degraded else 'none of these'}")
    print(f"Saved: {BASELINE_FOLDER / 'sweep.json'}")
    return 0


def confirm(host: str, base_users: int, repeats: int) -> int:
    """Run full replays at one level, keep their result files, and check that all degraded."""
    evaluations = []
    for index in range(repeats):
        if index:
            time.sleep(COOLDOWN_SECONDS)
        print(f"--- Full replay {index + 1} of {repeats} ---")
        evaluation = run_once(host, None, base_users)
        if evaluation is None:
            return 2
        evaluations.append(evaluation)
        kept_runs = BASELINE_FOLDER / "runs"
        kept_runs.mkdir(parents=True, exist_ok=True)
        source = run_replay.RUNS_FOLDER / f"{evaluation['run_id']}.json"
        shutil.copyfile(source, kept_runs / source.name)

    print_table(evaluations)
    summary = summarize_repeats(evaluations)
    first_run = json.loads((BASELINE_FOLDER / "runs" / f"{evaluations[0]['run_id']}.json").read_text(encoding="utf-8"))
    write_json(
        BASELINE_FOLDER / "failure_baseline.json",
        {
            "disclaimer": "Traffic is simulated. StatsBomb provides match events, not platform traffic. "
            "Measured on one machine, with the load generator on the same computer.",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "criteria": CRITERIA,
            "settings": {
                "base_users": base_users,
                "replay_seconds": first_run["settings"]["replay_seconds"],
                "peak_users": first_run["settings"]["peak_users"],
                "timeline_fingerprint": first_run["settings"]["timeline_fingerprint"],
                "protections": first_run["settings"]["protections"],
            },
            "environment": first_run["environment"],
            "runs": evaluations,
            "summary": summary,
        },
    )
    print(f"Repeatable failure: {summary['repeatable']} ({summary['degraded_runs']} of {summary['runs']} runs degraded)")
    print(f"Saved: {BASELINE_FOLDER / 'failure_baseline.json'}")
    return 0 if summary["repeatable"] else 1


# ===== Command line =====
def main(argv: list[str] | None = None) -> int:
    """Read the command and options, check them, and run the sweep or confirmation."""
    parser = argparse.ArgumentParser(description="Find and confirm the failure baseline.")
    commands = parser.add_subparsers(dest="command", required=True)
    sweep_parser = commands.add_parser("sweep", help="short replays at several load levels")
    sweep_parser.add_argument("--base-users", type=int, nargs="+", required=True)
    confirm_parser = commands.add_parser("confirm", help="repeated full replays at one level")
    confirm_parser.add_argument("--base-users", type=int, required=True)
    confirm_parser.add_argument("--repeats", type=int, default=REQUIRED_REPEATS)
    for command in (sweep_parser, confirm_parser):
        command.add_argument("--host", default=run_replay.DEFAULT_HOST)
    arguments = parser.parse_args(argv)

    try:
        host = require_local_target(arguments.host)
        levels = arguments.base_users if arguments.command == "sweep" else [arguments.base_users]
        for level in levels:
            build_plan(SHORT_REPLAY_SECONDS, level)
        if arguments.command == "confirm" and not 1 <= arguments.repeats <= 10:
            raise ValueError("Repeats must be 1 to 10.")
    except ValueError as error:
        print(f"Refused: {error}")
        return 2

    if arguments.command == "sweep":
        return sweep(host, sorted(set(levels)))
    return confirm(host, arguments.base_users, arguments.repeats)


if __name__ == "__main__":
    sys.exit(main())
