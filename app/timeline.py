"""Turn real match events and an assumed traffic profile into a repeatable replay timeline.

The events come from StatsBomb. The traffic is simulated: StatsBomb provides match events,
not platform traffic. Nothing here uses randomness or the clock, so the same inputs always
give the same output.
"""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = PROJECT_ROOT / "data" / "match_3869685_sample.json"
PROFILE_PATH = PROJECT_ROOT / "data" / "traffic_profile.json"
TIMELINE_PATH = PROJECT_ROOT / "data" / "timeline_3869685.json"

DISCLAIMER = (
    "Traffic is simulated. StatsBomb provides the match events, not platform traffic. "
    "Spike sizes and break lengths are assumptions."
)
PERIOD_NAMES = {
    1: "first_half",
    2: "second_half",
    3: "extra_time_first_half",
    4: "extra_time_second_half",
    5: "penalty_shootout",
}


# ===== Input formats =====
class StrictModel(BaseModel):
    """A model that rejects unknown fields, so that typos in data files are caught."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SampleSource(StrictModel):
    """Where the match sample came from."""

    provider: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    events_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str


class SampleMatch(StrictModel):
    """The match's identity and final score, excluding the shootout."""

    id: int = Field(ge=1)
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    competition: str = Field(min_length=1)
    season: str = Field(min_length=1)
    match_date: date
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)


class SampleEvent(StrictModel):
    """One key moment. Minutes are as StatsBomb gives them, so they overlap between periods."""

    period: int = Field(ge=1, le=5)
    minute: int = Field(ge=0, le=150)
    second: int = Field(ge=0, le=59)
    kind: Literal["period_start", "period_end", "goal", "shootout_goal", "shootout_miss"]
    team: str | None
    player: str | None
    description: str = Field(min_length=1)

    @property
    def stated_seconds(self) -> int:
        """Return the time as StatsBomb states it, in seconds."""
        return self.minute * 60 + self.second


class MatchSample(StrictModel):
    """A validated match sample: every period has one start and one end, in order."""

    source: SampleSource
    match: SampleMatch
    events: tuple[SampleEvent, ...]

    @model_validator(mode="after")
    def check_events(self) -> "MatchSample":
        """Reject samples whose periods or event order do not make sense."""
        periods = sorted({event.period for event in self.events})
        if not periods or periods != list(range(1, len(periods) + 1)):
            raise ValueError("periods must be consecutive and start at 1")

        order = [(event.period, event.stated_seconds) for event in self.events]
        if order != sorted(order):
            raise ValueError("events must be in time order within each period")

        for period in periods:
            rows = [event for event in self.events if event.period == period]
            if rows[0].kind != "period_start" or rows[-1].kind != "period_end":
                raise ValueError(f"period {period} must begin with its start and finish with its end")
            markers = [event for event in rows if event.kind in ("period_start", "period_end")]
            if len(markers) != 2:
                raise ValueError(f"period {period} must have exactly one start and one end")
        return self


class Spike(StrictModel):
    """Extra load added at a moment, fading to nothing over a number of replay seconds."""

    extra_load: float = Field(gt=0)
    duration_seconds: int = Field(ge=1)


class SpikeSet(StrictModel):
    """The spike used for each kind of moment."""

    goal: Spike
    shootout_kick: Spike
    final_kick: Spike
    match_break: Spike
    full_time: Spike


class TrafficProfile(StrictModel):
    """The assumptions that shape simulated traffic. None of these come from StatsBomb."""

    note: str
    replay_seconds: int = Field(ge=10)
    baseline: float = Field(gt=0)
    max_multiplier: float = Field(gt=0)
    post_match_seconds: int = Field(ge=0)
    break_seconds: dict[int, int]
    spikes: SpikeSet

    @model_validator(mode="after")
    def check_values(self) -> "TrafficProfile":
        """Reject a cap below the baseline, or a negative break."""
        if self.max_multiplier < self.baseline:
            raise ValueError("max_multiplier must not be below baseline")
        if any(seconds < 0 for seconds in self.break_seconds.values()):
            raise ValueError("break_seconds must not be negative")
        return self


# ===== Loading =====
def load_sample(path: Path = SAMPLE_PATH) -> MatchSample:
    """Read and validate a match sample."""
    return MatchSample.model_validate_json(path.read_text(encoding="utf-8"))


def load_profile(path: Path = PROFILE_PATH) -> TrafficProfile:
    """Read and validate a traffic profile."""
    return TrafficProfile.model_validate_json(path.read_text(encoding="utf-8"))


# ===== Match clock =====
def played_clock(sample: MatchSample) -> list[tuple[SampleEvent, int]]:
    """Pair each event with seconds played since kick-off, which never overlap between periods."""
    clock = []
    offset = 0
    period_start = 0
    for event in sample.events:
        if event.kind == "period_start":
            period_start = event.stated_seconds
        played = offset + event.stated_seconds - period_start
        clock.append((event, played))
        if event.kind == "period_end":
            offset = played
    return clock


# ===== Timeline =====
def spike_kind(event: SampleEvent, is_final_kick: bool, is_last_period: bool) -> str | None:
    """Choose which spike a moment triggers, or None if it triggers no spike."""
    if event.kind == "goal":
        return "goal"
    if event.kind in ("shootout_goal", "shootout_miss"):
        return "final_kick" if is_final_kick else "shootout_kick"
    if event.kind == "period_end":
        return "full_time" if is_last_period else "match_break"
    return None


def build_timeline(sample: MatchSample, profile: TrafficProfile) -> dict:
    """Build per-second load multipliers and labelled moments for one replay."""
    last_period = sample.events[-1].period
    missing = [p for p in range(1, last_period) if p not in profile.break_seconds]
    if missing:
        raise ValueError(f"break_seconds is missing period(s): {missing}")

    clock = played_clock(sample)
    kicks = [event for event in sample.events if event.kind.startswith("shootout_")]
    final_kick = kicks[-1] if kicks else None

    # ===== Stretch the match clock with assumed breaks, then compress it to the replay =====
    breaks_before = {
        period: sum(profile.break_seconds[p] for p in range(1, period))
        for period in range(1, last_period + 1)
    }
    total_seconds = clock[-1][1] + breaks_before[last_period] + profile.post_match_seconds
    scale = profile.replay_seconds / total_seconds

    def to_replay(event: SampleEvent, played: int) -> float:
        """Convert a moment to its time in the replay."""
        return round((played + breaks_before[event.period]) * scale, 3)

    # ===== Moments and phases =====
    moments = []
    phases = []
    for event, played in clock:
        replay_second = to_replay(event, played)
        if event.kind == "period_start":
            phases.append({"name": PERIOD_NAMES[event.period], "start_second": replay_second})
        elif event.kind == "period_end":
            name = "post_match" if event.period == last_period else f"break_after_{PERIOD_NAMES[event.period]}"
            phases.append({"name": name, "start_second": replay_second})

        kind = spike_kind(event, event is final_kick, event.period == last_period)
        if kind is not None:
            moments.append(
                {
                    "replay_second": replay_second,
                    "played_seconds": played,
                    "period": event.period,
                    "spike": kind,
                    "description": event.description,
                }
            )

    # ===== Per-second load =====
    points = []
    for second in range(profile.replay_seconds):
        multiplier = profile.baseline
        for moment in moments:
            spike = getattr(profile.spikes, moment["spike"])
            since = second - moment["replay_second"]
            if 0 <= since < spike.duration_seconds:
                multiplier += spike.extra_load * (1 - since / spike.duration_seconds)
        phase = [p["name"] for p in phases if p["start_second"] <= second][-1]
        points.append(
            {
                "second": second,
                "multiplier": round(min(multiplier, profile.max_multiplier), 3),
                "phase": phase,
            }
        )

    return {
        "disclaimer": DISCLAIMER,
        "match_id": sample.match.id,
        "replay_seconds": profile.replay_seconds,
        "match_seconds_per_replay_second": round(1 / scale, 3),
        "phases": phases,
        "moments": moments,
        "points": points,
    }


# ===== Output =====
def serialize(data: dict) -> str:
    """Write JSON in one fixed format, so that equal data always gives equal bytes."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fingerprint(data: dict) -> str:
    """Return a SHA-256 fingerprint of the serialized data."""
    return hashlib.sha256(serialize(data).encode("utf-8")).hexdigest()
