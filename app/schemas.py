"""The response formats the API promises to return."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ===== Health =====
class HealthOut(BaseModel):
    """The app is running and the database answered."""

    status: Literal["ok"]


# ===== Match =====
class MatchOut(BaseModel):
    """One match, including where its data came from."""

    id: int
    home_team: str
    away_team: str
    competition: str
    kickoff_at: datetime
    data_source: Literal["placeholder", "statsbomb"]


# ===== Feed =====
class EventOut(BaseModel):
    """One event in a match feed."""

    id: int
    minute: int
    second: int
    event_type: str
    team: str | None
    description: str


class FeedOut(BaseModel):
    """A page of a match's events."""

    match_id: int
    events: list[EventOut]


# ===== Stats =====
class MinuteStatsOut(BaseModel):
    """Generated fan reactions summarized for one minute."""

    minute: int
    total: int
    cheers: int
    groans: int
    gasps: int
    unique_fans: int


class MatchStatsOut(BaseModel):
    """The result of the deliberately slow per-minute summary."""

    match_id: int
    minutes: list[MinuteStatsOut]
