"""Build the small local match sample. Run with: python -m scripts.import_statsbomb

Only needed to regenerate the committed sample. The data comes from a fixed version of
StatsBomb's open data and is treated purely as data: it is parsed, checked, and never run.
Data source: StatsBomb (https://github.com/statsbomb/open-data).
"""

import hashlib
import json
import sys
import urllib.request

from app.timeline import SAMPLE_PATH, MatchSample, serialize

SOURCE_COMMIT = "4b73468fc5b0f1950f9f66fada70ad3a4f9327cb"
BASE_URL = f"https://raw.githubusercontent.com/statsbomb/open-data/{SOURCE_COMMIT}/data"
COMPETITION_ID = 43
SEASON_ID = 106
MATCH_ID = 3869685
SHOOTOUT_PERIOD = 5
TIMEOUT_SECONDS = 60


# ===== Download =====
def fetch(path: str) -> bytes:
    """Download one file from the pinned version of the data."""
    with urllib.request.urlopen(f"{BASE_URL}/{path}", timeout=TIMEOUT_SECONDS) as response:
        return response.read()


# ===== Extraction =====
def describe_shot(event: dict, team: str, player: str, outcome: str) -> str:
    """Write a short description of a goal or shootout kick."""
    if event["period"] == SHOOTOUT_PERIOD:
        result = "scored" if outcome == "Goal" else f"missed ({outcome})"
        return f"Shootout kick {result}: {player} ({team})"
    method = " from the penalty spot" if event["shot"]["type"]["name"] == "Penalty" else ""
    return f"Goal{method}: {player} ({team})"


def extract_events(events: list[dict]) -> list[dict]:
    """Keep only period starts and ends, goals, and shootout kicks."""
    sample = []
    seen_markers = set()
    for event in events:
        kind_name = event["type"]["name"]
        period = event["period"]
        if kind_name in ("Half Start", "Half End"):
            # StatsBomb records each marker once per team; one is enough.
            kind = "period_start" if kind_name == "Half Start" else "period_end"
            if (period, kind) not in seen_markers:
                seen_markers.add((period, kind))
                label = "starts" if kind == "period_start" else "ends"
                sample.append(_row(event, kind, None, None, f"Period {period} {label}"))
        elif kind_name == "Shot":
            outcome = event["shot"]["outcome"]["name"]
            team = event["team"]["name"]
            player = event["player"]["name"]
            if period == SHOOTOUT_PERIOD:
                kind = "shootout_goal" if outcome == "Goal" else "shootout_miss"
            elif outcome == "Goal":
                kind = "goal"
            else:
                continue
            sample.append(_row(event, kind, team, player, describe_shot(event, team, player, outcome)))
    return sample


def _row(event: dict, kind: str, team: str | None, player: str | None, description: str) -> dict:
    """Build one sample row."""
    return {
        "period": event["period"],
        "minute": event["minute"],
        "second": event["second"],
        "kind": kind,
        "team": team,
        "player": player,
        "description": description,
    }


def build_sample(match: dict, events: list[dict], events_sha256: str) -> dict:
    """Build the sample and check that its goals add up to the official score."""
    rows = extract_events(events)
    home = match["home_team"]["home_team_name"]
    away = match["away_team"]["away_team_name"]
    goals = [row["team"] for row in rows if row["kind"] == "goal"]
    if goals.count(home) != match["home_score"] or goals.count(away) != match["away_score"]:
        raise ValueError("Extracted goals do not match the final score")

    sample = {
        "source": {
            "provider": "StatsBomb Open Data",
            "commit": SOURCE_COMMIT,
            "events_sha256": events_sha256,
            "note": "Key moments only. StatsBomb provides match events, not platform traffic.",
        },
        "match": {
            "id": match["match_id"],
            "home_team": home,
            "away_team": away,
            "competition": match["competition"]["competition_name"],
            "season": match["season"]["season_name"],
            "match_date": match["match_date"],
            "home_score": match["home_score"],
            "away_score": match["away_score"],
        },
        "events": rows,
    }
    MatchSample.model_validate(sample)
    return sample


# ===== Command line =====
def main() -> int:
    """Download the match, build the sample, and write it to the data folder."""
    matches = json.loads(fetch(f"matches/{COMPETITION_ID}/{SEASON_ID}.json"))
    match = next(row for row in matches if row["match_id"] == MATCH_ID)
    raw_events = fetch(f"events/{MATCH_ID}.json")
    sample = build_sample(match, json.loads(raw_events), hashlib.sha256(raw_events).hexdigest())
    SAMPLE_PATH.write_text(serialize(sample), encoding="utf-8", newline="\n")
    print(f"Wrote {len(sample['events'])} events to {SAMPLE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
