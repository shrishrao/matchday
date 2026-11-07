"""Turn the timeline into simulated user counts. This module does not import Locust."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.timeline import TrafficProfile, build_timeline, fingerprint, load_profile, load_sample

DEFAULT_BASE_USERS = 5
MAX_BASE_USERS = 500
MIN_REPLAY_SECONDS = 10
MAX_REPLAY_SECONDS = 3_600
SHORT_REPLAY_SECONDS = 30
TRACE_REQUIRED_SHARE = 0.9
# Stopping fans finish their current request first (Locust --stop-timeout 12), so after a
# spike the user count may stay above the new target for up to this long.
STOP_GRACE_SECONDS = 13

REPLAY_SECONDS_VARIABLE = "MATCHDAY_REPLAY_SECONDS"
BASE_USERS_VARIABLE = "MATCHDAY_BASE_USERS"
TRACE_PATH_VARIABLE = "MATCHDAY_TRACE_PATH"
REQUESTS_PATH_VARIABLE = "MATCHDAY_REQUESTS_PATH"


# ===== Plan =====
@dataclass(frozen=True)
class ReplayPlan:
    """The simulated user count for each second of one replay."""

    match_id: int
    base_users: int
    targets: tuple[int, ...]
    phases: tuple[str, ...]
    moments: tuple[tuple[float, str], ...]
    timeline_fingerprint: str

    @property
    def peak_users(self) -> int:
        """Return the largest user count in the replay."""
        return max(self.targets)

    @property
    def spawn_rate(self) -> int:
        """Return a start rate that can reach any user count within one second."""
        return self.peak_users

    def target_at(self, run_time: float) -> int | None:
        """Return the user count for a moment in the replay, or None once it has finished."""
        second = int(run_time)
        return self.targets[second] if second < len(self.targets) else None


def users_for(multiplier: float, base_users: int) -> int:
    """Convert a load multiplier to a whole user count of at least one."""
    return max(1, round(multiplier * base_users))


def scale_profile(profile: TrafficProfile, replay_seconds: int) -> TrafficProfile:
    """Fit a profile to another replay length, shrinking spikes so that they keep their shape."""
    data = profile.model_dump()
    data["replay_seconds"] = replay_seconds
    ratio = replay_seconds / profile.replay_seconds
    for spike in data["spikes"].values():
        spike["duration_seconds"] = max(1, round(spike["duration_seconds"] * ratio))
    return TrafficProfile.model_validate(data)


def build_plan(replay_seconds: int | None = None, base_users: int = DEFAULT_BASE_USERS) -> ReplayPlan:
    """Build the plan for a replay. Without a length, it uses the profile's full replay."""
    profile = load_profile()
    seconds = profile.replay_seconds if replay_seconds is None else replay_seconds
    validate_settings(seconds, base_users)
    timeline = build_timeline(load_sample(), scale_profile(profile, seconds))
    return ReplayPlan(
        match_id=timeline["match_id"],
        base_users=base_users,
        targets=tuple(users_for(point["multiplier"], base_users) for point in timeline["points"]),
        phases=tuple(point["phase"] for point in timeline["points"]),
        moments=tuple((moment["replay_second"], moment["description"]) for moment in timeline["moments"]),
        timeline_fingerprint=fingerprint(timeline),
    )


# ===== Settings =====
def validate_settings(replay_seconds: int, base_users: int) -> None:
    """Reject a replay length or user count outside the supported limits."""
    if not MIN_REPLAY_SECONDS <= replay_seconds <= MAX_REPLAY_SECONDS:
        raise ValueError(f"Replay length must be {MIN_REPLAY_SECONDS} to {MAX_REPLAY_SECONDS} seconds.")
    if not 1 <= base_users <= MAX_BASE_USERS:
        raise ValueError(f"Base users must be 1 to {MAX_BASE_USERS}.")


def plan_from_environment(env: Mapping[str, str]) -> ReplayPlan:
    """Build a plan from environment variables, using the defaults for any that are not set."""
    seconds = env.get(REPLAY_SECONDS_VARIABLE)
    return build_plan(
        replay_seconds=int(seconds) if seconds else None,
        base_users=int(env.get(BASE_USERS_VARIABLE, DEFAULT_BASE_USERS)),
    )


# ===== Trace comparison =====
def summarize_trace(rows: Sequence[Mapping[str, int]], grace_seconds: int = STOP_GRACE_SECONDS) -> dict:
    """Compare asked-for and actual users, read one second later to allow for start-up.

    A second is on target if the actual users reached the target, and were no higher than the
    largest target of the last grace_seconds (fans still finishing their last request).
    """
    if len(rows) < 2:
        return {
            "seconds": 0, "share_on_target": 0.0, "below_target_seconds": 0, "above_allowed_seconds": 0,
            "largest_gap": 0, "peak_actual": 0, "follows_timeline": False,
        }

    below = above = 0
    for index, (row, following) in enumerate(zip(rows, rows[1:])):
        target, actual = row["target"], following["actual"]
        allowed = max(r["target"] for r in rows[max(0, index - grace_seconds): index + 1])
        if actual < target - max(1, target // 10):
            below += 1
        elif actual > allowed + max(1, allowed // 10):
            above += 1

    seconds = len(rows) - 1
    share = (seconds - below - above) / seconds
    return {
        "seconds": seconds,
        "share_on_target": round(share, 3),
        "below_target_seconds": below,
        "above_allowed_seconds": above,
        "largest_gap": max(abs(f["actual"] - r["target"]) for r, f in zip(rows, rows[1:])),
        "peak_actual": max(f["actual"] for f in rows[1:]),
        "follows_timeline": share >= TRACE_REQUIRED_SHARE,
    }
