"""The simulated crowd. Traffic is simulated; StatsBomb provides match events, not platform traffic.

Start replays with: python -m scripts.run_replay
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from locust import HttpUser, LoadTestShape, between, events, task

from loadgen.safety import UnsafeTargetError, require_local_target, require_safe_run_mode
from loadgen.schedule import REQUESTS_PATH_VARIABLE, TRACE_PATH_VARIABLE, plan_from_environment

PLAN = plan_from_environment(os.environ)
REQUEST_TIMEOUT_SECONDS = 10
PROGRESS_EVERY_SECONDS = 15
REFUSED_EXIT_CODE = 2

trace: list[dict] = []
request_log = None


# ===== Safety =====
@events.init.add_listener
def refuse_unsafe_runs(environment, **_) -> None:
    """Stop the process immediately, before any user starts, if the target or mode is unsafe."""
    options = environment.parsed_options
    try:
        require_local_target(environment.host)
        require_safe_run_mode(options.headless, options.master, options.worker)
    except UnsafeTargetError as error:
        print(f"Refused: {error}", file=sys.stderr, flush=True)
        os._exit(REFUSED_EXIT_CODE)


# ===== Request records =====
@events.test_start.add_listener
def open_request_log(**_) -> None:
    """Open the request record file, if the run command asked for one."""
    global request_log
    path = os.environ.get(REQUESTS_PATH_VARIABLE)
    if path:
        request_log = open(path, "w", encoding="utf-8")


@events.request.add_listener
def record_request(name, response_time, exception, **_) -> None:
    """Write one line per finished request: its name, time taken, and whether it failed."""
    if request_log is not None:
        request_log.write(
            json.dumps(
                {
                    "name": name,
                    "end_time": time.time(),
                    "response_time_ms": response_time,
                    "failed": exception is not None,
                }
            )
            + "\n"
        )


# ===== Simulated fans =====
class Fan(HttpUser):
    """One simulated fan. The mix of requests is an assumption, not measured behaviour."""

    wait_time = between(0.5, 1.5)

    def fetch(self, path: str, name: str) -> None:
        """Send one request. Redirects are not followed, so a reply cannot send traffic elsewhere."""
        self.client.get(path, name=name, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    @task(7)
    def read_feed(self) -> None:
        """Check the match feed: the fast, indexed path."""
        self.fetch(f"/matches/{PLAN.match_id}/feed", "/matches/[id]/feed")

    @task(2)
    def read_match(self) -> None:
        """Check the score and match details."""
        self.fetch(f"/matches/{PLAN.match_id}", "/matches/[id]")

    @task(1)
    def read_stats(self) -> None:
        """Open the per-minute stats: the deliberately slow path."""
        self.fetch(f"/matches/{PLAN.match_id}/stats", "/matches/[id]/stats")


# ===== Load shape =====
class ReplayShape(LoadTestShape):
    """Follow the timeline's user count, once per second, and end when the replay ends."""

    next_moment = 0

    def tick(self) -> tuple[int, int] | None:
        """Report progress, record the asked-for and actual users, and return the next target."""
        run_time = self.get_run_time()
        target = PLAN.target_at(run_time)
        if target is None:
            return None

        second = int(run_time)
        actual = self.get_current_user_count()
        trace.append({"second": second, "time": time.time(), "target": target, "actual": actual})

        while self.next_moment < len(PLAN.moments) and PLAN.moments[self.next_moment][0] <= run_time:
            print(f"[{second:>4}s] {PLAN.moments[self.next_moment][1]}", flush=True)
            self.next_moment += 1
        if second % PROGRESS_EVERY_SECONDS == 0:
            print(f"[{second:>4}s] {PLAN.phases[second]}: {actual} users, moving to {target}", flush=True)
        return target, PLAN.spawn_rate


# ===== Trace output =====
@events.quitting.add_listener
def save_trace(**_) -> None:
    """Close the request records and save the per-second user record, if asked for."""
    if request_log is not None:
        request_log.close()
    path = os.environ.get(TRACE_PATH_VARIABLE)
    if path:
        Path(path).write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
