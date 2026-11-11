"""The Matchday API: a small match feed with one deliberately slow endpoint."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import FastAPI, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from app import queries
from app.cache import CacheStatus, cached, create_cache
from app.config import Settings
from app.db import create_pool
from app.metrics import COUNTERS
from app.schemas import FeedOut, HealthOut, MatchOut, MatchStatsOut, MetricsOut

# ===== Input limits =====
MAX_BIGINT = 2**63 - 1
MAX_CLOCK_SECONDS = 14_400
MAX_FEED_LIMIT = 100
CACHE_HEADER = "X-Cache"

MatchId = Annotated[int, Path(ge=1, le=MAX_BIGINT)]


# ===== Helpers =====
def require_match(connection: psycopg.Connection, match_id: int) -> dict:
    """Return the match, or stop the request with a 404."""
    match = queries.get_match(connection, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


def with_connection(request: Request, work: Callable[[psycopg.Connection], dict]) -> Callable[[], dict]:
    """Wrap database work so it borrows a pool connection only when it actually runs.

    Routes use this instead of a FastAPI "yield" dependency, for two reasons (DECISIONS.md D39):
    a dependency borrows before the route starts, so even cache hits would queue for a
    connection; and a sync dependency needs a second worker thread to hand the connection
    back, so when every thread is waiting for a connection, none can be returned. Here the
    connection is borrowed and returned in the same thread.
    """

    def load() -> dict:
        with request.app.state.pool.connection() as connection:
            return work(connection)

    return load


def mark_cache(response: Response, status: CacheStatus) -> None:
    """Tell the caller whether this answer came from the cache."""
    response.headers[CACHE_HEADER] = status.value


# ===== App factory =====
def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API, using the given settings or those from the environment."""
    active_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the connection pool and cache at startup, and close them at shutdown."""
        app.state.pool = create_pool(active_settings)
        app.state.pool.open()
        app.state.cache = create_cache(active_settings)
        yield
        if app.state.cache is not None:
            app.state.cache.close()
        app.state.pool.close()

    app = FastAPI(
        title="Matchday API",
        description=(
            "Traffic is simulated and fan reactions are generated. "
            "Match events: StatsBomb, which provides match events, not platform traffic."
        ),
        lifespan=lifespan,
    )

    # ===== Error handling =====
    @app.exception_handler(psycopg.OperationalError)
    def database_unavailable(_: Request, __: psycopg.OperationalError) -> JSONResponse:
        """Answer 503 when the database or pool is unavailable, hiding internal details."""
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable"},
            headers={"Retry-After": "5"},
        )

    # ===== Routes =====
    @app.get("/health", response_model=HealthOut)
    def health(request: Request) -> dict:
        """Report that the app is running and the database answers. Never cached."""
        with request.app.state.pool.connection() as connection:
            queries.ping(connection)
        return {"status": "ok"}

    @app.get("/internal/metrics", response_model=MetricsOut)
    async def read_metrics(request: Request) -> dict:
        """Report server counters, pool pressure and active protections. Uses no database connection.

        It is async so that it runs on the event loop rather than the route thread pool,
        and stays readable when every route thread is busy. It only reads memory.
        This is safe here because the API only listens on 127.0.0.1. A public deployment
        would need to protect it.
        """
        cache_enabled = request.app.state.cache is not None
        stats = request.app.state.pool.get_stats()
        return {
            **COUNTERS.snapshot(cache_enabled),
            "pool": {
                "size": stats.get("pool_size", 0),
                "available": stats.get("pool_available", 0),
                "waiting": stats.get("requests_waiting", 0),
                "failed_requests": stats.get("requests_errors", 0),
            },
            "protections": {
                "cache": cache_enabled,
                "stampede_lock": False,
                "rate_limit": False,
                "load_shedding": False,
            },
        }

    @app.get("/matches/{match_id}", response_model=MatchOut)
    def read_match(match_id: MatchId, request: Request, response: Response) -> MatchOut:
        """Return one match."""
        cache = request.app.state.cache
        result, status = cached(
            cache,
            cache.match_key(match_id) if cache else "",
            active_settings.cache_ttl_match_seconds,
            MatchOut,
            with_connection(request, lambda connection: require_match(connection, match_id)),
        )
        mark_cache(response, status)
        return result

    @app.get("/matches/{match_id}/feed", response_model=FeedOut)
    def read_feed(
        match_id: MatchId,
        request: Request,
        response: Response,
        after_seconds: Annotated[int | None, Query(ge=0, le=MAX_CLOCK_SECONDS)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_FEED_LIMIT)] = 50,
    ) -> FeedOut:
        """Return a match's events in time order. This is the fast, indexed path."""

        def load(connection: psycopg.Connection) -> dict:
            require_match(connection, match_id)
            events = queries.get_feed(connection, match_id, after_seconds, limit)
            return {"match_id": match_id, "events": events}

        cache = request.app.state.cache
        result, status = cached(
            cache,
            cache.feed_key(match_id, after_seconds, limit) if cache else "",
            active_settings.cache_ttl_feed_seconds,
            FeedOut,
            with_connection(request, load),
        )
        mark_cache(response, status)
        return result

    @app.get("/matches/{match_id}/stats", response_model=MatchStatsOut)
    def read_stats(match_id: MatchId, request: Request, response: Response) -> MatchStatsOut:
        """Return per-minute reaction totals. This is the deliberately slow path."""

        def load(connection: psycopg.Connection) -> dict:
            require_match(connection, match_id)
            return {"match_id": match_id, "minutes": queries.get_match_stats(connection, match_id)}

        cache = request.app.state.cache
        result, status = cached(
            cache,
            cache.stats_key(match_id) if cache else "",
            active_settings.cache_ttl_stats_seconds,
            MatchStatsOut,
            with_connection(request, load),
        )
        mark_cache(response, status)
        return result

    return app


app = create_app()
