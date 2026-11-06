"""Tests proving that the same inputs always produce the same timeline."""

import pytest
from pydantic import ValidationError

from app.timeline import (
    DISCLAIMER,
    TIMELINE_PATH,
    MatchSample,
    TrafficProfile,
    build_timeline,
    fingerprint,
    load_profile,
    load_sample,
    serialize,
)

# Change this only when a change to the timeline is intended, and explain why in the commit.
EXPECTED_FINGERPRINT = "2ada46e3ea75793636f1add8dea6b8ca4b06bb0429ea11572f12a4d62daef733"


# ===== Fixtures and helpers =====
@pytest.fixture
def sample():
    return load_sample()


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def timeline(sample, profile):
    return build_timeline(sample, profile)


def changed_sample(sample, **changes):
    """Copy the sample's data with changed top-level fields, re-validating it."""
    return MatchSample.model_validate({**sample.model_dump(), **changes})


def changed_profile(profile, **changes):
    """Copy the profile's data with changed fields, re-validating it."""
    return TrafficProfile.model_validate({**profile.model_dump(), **changes})


# ===== Repeatability =====
def test_same_input_gives_byte_identical_output(sample, profile):
    assert serialize(build_timeline(sample, profile)) == serialize(build_timeline(sample, profile))


def test_reloading_the_files_gives_the_same_output():
    first = build_timeline(load_sample(), load_profile())
    second = build_timeline(load_sample(), load_profile())
    assert fingerprint(first) == fingerprint(second)


def test_timeline_matches_the_stored_fingerprint(timeline):
    assert fingerprint(timeline) == EXPECTED_FINGERPRINT


def test_committed_timeline_file_is_up_to_date(timeline):
    assert TIMELINE_PATH.read_text(encoding="utf-8") == serialize(timeline)


# ===== Changing inputs changes the output =====
def test_moving_a_goal_changes_the_timeline(sample, profile, timeline):
    rows = sample.model_dump()["events"]
    goal = next(row for row in rows if row["kind"] == "goal")
    goal["minute"] += 5
    moved = changed_sample(sample, events=rows)
    assert fingerprint(build_timeline(moved, profile)) != fingerprint(timeline)


def test_changing_the_profile_changes_the_timeline(sample, profile, timeline):
    bigger = profile.model_dump()
    bigger["spikes"]["goal"]["extra_load"] = 6.5
    assert fingerprint(build_timeline(sample, changed_profile(profile, **bigger))) != fingerprint(timeline)


# ===== Timeline shape =====
def test_timeline_covers_the_three_minute_replay(timeline):
    assert timeline["replay_seconds"] == 180
    assert [point["second"] for point in timeline["points"]] == list(range(180))


def test_timeline_states_that_traffic_is_simulated(timeline):
    assert timeline["disclaimer"] == DISCLAIMER
    assert "simulated" in DISCLAIMER
    assert "not platform traffic" in DISCLAIMER


def test_moments_are_all_goals_kicks_breaks_and_full_time(timeline):
    spikes = [moment["spike"] for moment in timeline["moments"]]
    assert spikes.count("goal") == 6
    assert spikes.count("shootout_kick") == 7
    assert spikes.count("final_kick") == 1
    assert spikes.count("match_break") == 4
    assert spikes.count("full_time") == 1


def test_moments_and_phases_are_in_time_order_inside_the_replay(timeline):
    moment_times = [moment["replay_second"] for moment in timeline["moments"]]
    phase_times = [phase["start_second"] for phase in timeline["phases"]]
    assert moment_times == sorted(moment_times)
    assert phase_times == sorted(phase_times)
    assert 0 <= moment_times[0] and moment_times[-1] < 180


def test_load_rises_after_every_goal(timeline, profile):
    points = timeline["points"]
    for moment in timeline["moments"]:
        if moment["spike"] == "goal":
            second = int(moment["replay_second"]) + 1
            assert points[second]["multiplier"] > profile.baseline


def test_load_is_at_baseline_when_nothing_is_happening(timeline, profile):
    assert timeline["points"][0]["multiplier"] == profile.baseline


def test_load_stays_between_baseline_and_cap(timeline, profile):
    multipliers = [point["multiplier"] for point in timeline["points"]]
    assert min(multipliers) >= profile.baseline
    assert max(multipliers) <= profile.max_multiplier


def test_cap_is_applied(sample, profile):
    capped = build_timeline(sample, changed_profile(profile, max_multiplier=2.0))
    assert max(point["multiplier"] for point in capped["points"]) == 2.0


def test_phases_follow_the_match(timeline):
    names = [phase["name"] for phase in timeline["phases"]]
    assert names[0] == "first_half"
    assert names[-2] == "penalty_shootout"
    assert names[-1] == "post_match"
    assert timeline["points"][-1]["phase"] == "post_match"


# ===== Invalid inputs =====
def test_missing_break_is_rejected(sample, profile):
    incomplete = changed_profile(profile, break_seconds={1: 900})
    with pytest.raises(ValueError, match="break_seconds"):
        build_timeline(sample, incomplete)


@pytest.mark.parametrize(
    "changes",
    [
        {"replay_seconds": 0},
        {"baseline": 0},
        {"max_multiplier": 0.5},
        {"post_match_seconds": -1},
        {"break_seconds": {1: -1}},
        {"unexpected_field": 1},
    ],
)
def test_invalid_profile_is_rejected(profile, changes):
    with pytest.raises(ValidationError):
        changed_profile(profile, **changes)


def test_events_out_of_order_are_rejected(sample):
    rows = list(sample.model_dump()["events"])
    rows[1], rows[2] = rows[2], rows[1]
    with pytest.raises(ValidationError):
        changed_sample(sample, events=rows)


def test_missing_period_end_is_rejected(sample):
    rows = [row for row in sample.model_dump()["events"] if not (row["period"] == 1 and row["kind"] == "period_end")]
    with pytest.raises(ValidationError):
        changed_sample(sample, events=rows)


def test_skipped_period_is_rejected(sample):
    rows = [row for row in sample.model_dump()["events"] if row["period"] != 2]
    with pytest.raises(ValidationError):
        changed_sample(sample, events=rows)


def test_invalid_event_kind_is_rejected(sample):
    rows = sample.model_dump()["events"]
    rows[1]["kind"] = "nonsense"
    with pytest.raises(ValidationError):
        changed_sample(sample, events=rows)
