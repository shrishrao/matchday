"""The response formats the API promises to return."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


# ===== Health =====
class HealthOut(BaseModel):
    """The app is running and the database answered."""

    status: Literal["ok"]


# ===== Server metrics =====
class CacheMetricsOut(BaseModel):
    """Cache counters. None means not measured, because the cache is off."""

    enabled: bool
    hits: int | None
    misses: int | None
    errors: int | None


class ProtectionsOut(BaseModel):
    """Which protections this API process is running with."""

    cache: bool
    stampede_lock: bool
    rate_limit: bool
    load_shedding: bool


class PoolMetricsOut(BaseModel):
    """The connection pool right now, plus failed connection requests since startup."""

    size: int
    available: int
    waiting: int
    failed_requests: int


class MetricsOut(BaseModel):
    """Running totals since the API process started."""

    db_queries_total: int
    cache: CacheMetricsOut
    pool: PoolMetricsOut
    protections: ProtectionsOut


# ===== Match =====
class MatchOut(BaseModel):
    """One match, including where its data came from."""

    id: int
    home_team: str
    away_team: str
    competition: str
    season: str
    match_date: date
    home_score: int
    away_score: int
    data_source: Literal["statsbomb"]


# ===== Feed =====
class EventOut(BaseModel):
    """One event in a match feed. clock_seconds gives its true order."""

    id: int
    period: int
    minute: int
    second: int
    clock_seconds: int
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
