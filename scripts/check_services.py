"""Check that Postgres and Redis accept connections and answer real commands."""

import os
import sys
import uuid
from dataclasses import dataclass
from typing import Mapping

import psycopg
import redis
from dotenv import load_dotenv

REQUIRED_SETTINGS = (
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "REDIS_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
)
TIMEOUT_SECONDS = 3


# ===== Data types =====
@dataclass(frozen=True)
class CheckResult:
    """The outcome of checking one service."""

    name: str
    ok: bool
    detail: str


# ===== Settings =====
def load_settings(env: Mapping[str, str]) -> dict[str, str]:
    """Return the required settings, raising ValueError if any are missing or empty."""
    missing = [key for key in REQUIRED_SETTINGS if not env.get(key)]
    if missing:
        raise ValueError(f"Missing settings: {', '.join(missing)}. Copy .env.example to .env.")
    return {key: env[key] for key in REQUIRED_SETTINGS}


def safe_error(error: Exception, secret: str) -> str:
    """Describe an error on one line, with the password removed."""
    lines = str(error).strip().splitlines()
    message = lines[0] if lines else type(error).__name__
    return message.replace(secret, "***")


# ===== Service checks =====
def check_postgres(settings: Mapping[str, str]) -> CheckResult:
    """Connect to Postgres and run a real query, returning a failure instead of raising."""
    try:
        with psycopg.connect(
            host=settings["POSTGRES_HOST"],
            port=int(settings["POSTGRES_PORT"]),
            user=settings["POSTGRES_USER"],
            password=settings["POSTGRES_PASSWORD"],
            dbname=settings["POSTGRES_DB"],
            connect_timeout=TIMEOUT_SECONDS,
        ) as connection:
            version = connection.execute("SHOW server_version").fetchone()[0]
        return CheckResult("postgres", True, f"server version {version}")
    except (psycopg.Error, ValueError) as error:
        return CheckResult("postgres", False, safe_error(error, settings["POSTGRES_PASSWORD"]))


def check_redis(settings: Mapping[str, str]) -> CheckResult:
    """Write, read and delete a temporary key, returning a failure instead of raising."""
    key = f"matchday:healthcheck:{uuid.uuid4().hex}"
    client = None
    try:
        client = redis.Redis(
            host=settings["REDIS_HOST"],
            port=int(settings["REDIS_PORT"]),
            password=settings["REDIS_PASSWORD"],
            socket_connect_timeout=TIMEOUT_SECONDS,
            socket_timeout=TIMEOUT_SECONDS,
            decode_responses=True,
        )
        client.set(key, "ok", ex=30)
        if client.get(key) != "ok":
            return CheckResult("redis", False, "read back the wrong value")
        client.delete(key)
        return CheckResult("redis", True, f"server version {client.info('server')['redis_version']}")
    except (redis.RedisError, ValueError) as error:
        return CheckResult("redis", False, safe_error(error, settings["REDIS_PASSWORD"]))
    finally:
        if client is not None:
            client.close()


# ===== Command line =====
def main() -> int:
    """Run both checks, print the results, and return 0 only if both pass."""
    load_dotenv()
    try:
        settings = load_settings(os.environ)
    except ValueError as error:
        print(f"[FAIL] settings: {error}")
        return 1

    results = [check_postgres(settings), check_redis(settings)]
    for result in results:
        print(f"[{'PASS' if result.ok else 'FAIL'}] {result.name}: {result.detail}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
