"""Tests for the StatsBomb importer and the committed match sample."""

import pytest

from app.timeline import load_sample, played_clock
from scripts.import_statsbomb import build_sample, extract_events

SHA = "a" * 64
MATCH = {
    "match_id": 1,
    "home_team": {"home_team_name": "Home"},
    "away_team": {"away_team_name": "Away"},
    "competition": {"competition_name": "Cup"},
    "season": {"season_name": "2022"},
    "match_date": "2022-12-18",
    "home_score": 1,
    "away_score": 0,
}


# ===== Helpers =====
def marker(name, period, minute, team="Home"):
    """Build a raw period marker."""
    return {
        "type": {"name": name},
        "period": period,
        "minute": minute,
        "second": 0,
        "team": {"name": team},
    }


def shot(outcome, period=1, minute=10, shot_type="Open Play"):
    """Build a raw shot."""
    return {
        "type": {"name": "Shot"},
        "period": period,
        "minute": minute,
        "second": 30,
        "team": {"name": "Home"},
        "player": {"name": "A Player"},
        "shot": {"outcome": {"name": outcome}, "type": {"name": shot_type}},
    }


def raw_events():
    """Build a small raw match with one goal and unneeded events."""
    return [
        marker("Half Start", 1, 0),
        marker("Half Start", 1, 0, team="Away"),
        {"type": {"name": "Pass"}, "period": 1, "minute": 1, "second": 0},
        shot("Saved", minute=5),
        shot("Goal"),
        marker("Half End", 1, 45),
        marker("Half End", 1, 45, team="Away"),
    ]


# ===== Extraction =====
def test_extract_keeps_only_key_moments_and_one_marker_per_period():
    kinds = [row["kind"] for row in extract_events(raw_events())]
    assert kinds == ["period_start", "goal", "period_end"]


def test_extract_includes_missed_shootout_kicks():
    events = [
        marker("Half Start", 5, 120),
        shot("Saved", period=5, minute=121, shot_type="Penalty"),
        shot("Goal", period=5, minute=122, shot_type="Penalty"),
        marker("Half End", 5, 123),
    ]
    kinds = [row["kind"] for row in extract_events(events)]
    assert kinds == ["period_start", "shootout_miss", "shootout_goal", "period_end"]


def test_build_sample_accepts_a_matching_score():
    sample = build_sample(MATCH, raw_events(), SHA)
    assert sample["source"]["events_sha256"] == SHA


def test_build_sample_rejects_a_score_mismatch():
    with pytest.raises(ValueError, match="final score"):
        build_sample({**MATCH, "home_score": 2}, raw_events(), SHA)


# ===== The committed sample =====
def test_sample_is_the_real_final():
    match = load_sample().match
    assert match.id == 3869685
    assert (match.home_team, match.home_score, match.away_score, match.away_team) == (
        "Argentina",
        3,
        3,
        "France",
    )


def test_sample_goals_are_at_the_real_times():
    goals = [
        (event.period, event.minute, event.second, event.team)
        for event in load_sample().events
        if event.kind == "goal"
    ]
    assert goals == [
        (1, 22, 24, "Argentina"),
        (1, 35, 22, "Argentina"),
        (2, 79, 24, "France"),
        (2, 80, 59, "France"),
        (4, 107, 58, "Argentina"),
        (4, 117, 5, "France"),
    ]


def test_sample_has_the_real_shootout():
    kicks = [event for event in load_sample().events if event.kind.startswith("shootout_")]
    assert len(kicks) == 8
    assert sum(event.kind == "shootout_miss" for event in kicks) == 2
    assert kicks[-1].team == "Argentina"
    assert kicks[-1].kind == "shootout_goal"


def test_sample_is_small():
    assert len(load_sample().events) == 24


def test_played_clock_never_goes_backwards_despite_overlapping_minutes():
    clock = [played for _, played in played_clock(load_sample())]
    assert clock == sorted(clock)
    # First half: 52:34 played, so the second half's goal at stated 79:24 is 34:24 after that.
    second_half_goal = next(played for event, played in played_clock(load_sample()) if event.minute == 79)
    assert second_half_goal == (52 * 60 + 34) + (34 * 60 + 24)
