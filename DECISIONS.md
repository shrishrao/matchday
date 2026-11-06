# Decisions

Each entry: decision, alternatives considered, and tradeoffs.

## D1: Project lives at `C:\dev\matchday`, not in OneDrive (Stage 0)
- **Decision:** keep the repo outside OneDrive.
- **Alternatives:** the original `Desktop\Shrish\Fun\Matchday` folder (synced by OneDrive).
- **Why:** OneDrive syncing locks and re-uploads files while `.venv`, git and result files change rapidly. That causes "file in use" errors and slowdowns. Git plus GitHub is the backup instead.

## D2: Python 3.13 (Stage 0)
- **Decision:** create the virtual environment with Python 3.13.7, which is already installed.
- **Alternatives:** 3.10 (the default on PATH; past end of security support as of Oct 2026), 3.14 (newest; some compiled packages may lag behind), 3.12 (would need a new install).
- **Why:** 3.13 is mature and supported, and needs no download.

## D3: `venv` + `requirements.txt` for dependencies (Stage 0)
- **Decision:** use the standard library `venv` and pinned `requirements.txt` files.
- **Alternatives:** `uv`, Poetry.
- **Why:** nothing extra to install or learn; pinned versions keep runs reproducible. Tradeoff: slower installs, no automatic lock file.

## D4: Match = 2022 World Cup final, Argentina vs France (Stage 0)
- **Decision:** use this match from StatsBomb open data.
- **Why:** 6 goals in normal and extra time, plus a penalty shootout, give many distinct, explainable spikes.
- **Tradeoff:** the full event file is large; Stage 3 stores only a small extracted sample.

## D5: Line endings normalized to LF via `.gitattributes` (Stage 0)
- **Why:** files are edited on Windows but run inside Linux containers. LF in git avoids noisy diffs and broken shell scripts in containers.

## D6: Default git branch is `main` (Stage 0)
- **Why:** matches the current GitHub default.

## D7: Pin exact images: `postgres:18.6-alpine`, `redis:8.10.3-alpine` (Stage 1)
- **Alternatives:** `latest`, or major-only tags such as `18-alpine`.
- **Why:** a silent image update could change benchmark results between runs. Alpine images are smaller.
- **Tradeoff:** security patches arrive only when we bump the tag by hand. Postgres 18 also mounts its volume at `/var/lib/postgresql`, not the older `/var/lib/postgresql/data`.

## D8: Local-only ports, and passwords on both services (Stage 1)
- **Alternative:** Compose's default port publishing, which listens on all network interfaces, and no password on Redis.
- **Why:** binding to `127.0.0.1` keeps other devices on the network out. The Redis password adds a second layer.
- **Tradeoff:** a little more setup in `.env`.

## D9: Redis saves nothing to disk (Stage 1)
- **Alternative:** Redis snapshots or append-only persistence.
- **Why:** Redis is only a cache here and Postgres is the source of truth. Starting empty also keeps benchmark runs comparable.
- **Tradeoff:** every restart begins with an empty cache.

## D10: Integration tests fail when services are down, rather than skip (Stage 1)
- **Alternative:** skip them automatically.
- **Why:** a skipped test can look like a pass and hide a broken setup.
- **Tradeoff:** services must be running for a full test pass.

## D11: Plain SQL through psycopg, no ORM (Stage 2)
- **Alternative:** SQLAlchemy.
- **Why:** every query stays visible, which helps with `EXPLAIN` and query counting in Stage 5.
- **Tradeoff:** more hand-written SQL, and result rows are not mapped to objects.

## D12: Regular `def` routes, not `async` (Stage 2)
- **Alternative:** `async def` with psycopg's async pool.
- **Why:** psycopg's async mode does not work with Windows' default event loop. FastAPI runs `def` routes in a thread pool, which is simpler to explain.
- **Tradeoff:** concurrency is limited by threads and pool size, which is a realistic failure point for Stage 6.

## D13: The slow query stays slow on purpose (Stage 2)
- **Decision:** `/stats` reads all 1,000,000 generated reactions and sorts them for `count(DISTINCT fan_id)`.
- **Alternative:** add an index or a pre-computed summary table.
- **Why:** this is the load the protections are measured against. An index on `match_id` would not help much with one match, because every row matches. A test keeps the table free of extra indexes.
- **Tradeoff:** the reactions are generated, and the README must say so.

## D14: Test each pooled connection before lending it (Stage 2)
- **Decision:** set `check=ConnectionPool.check_connection`.
- **Alternative:** the default, no check.
- **Why:** without it, the live API kept returning 503 after Postgres had restarted, because requests got dead connections.
- **Tradeoff:** one extra network round trip per request. It applies to every benchmark run equally, so comparisons stay fair.

## D15: Separate test database, and `httpx2` for the test client (Stage 2)
- **Why a separate database:** tests can reseed `matchday_test` without touching real seed data. Seeding also refuses non-local hosts because it erases data.
- **Why `httpx2`:** it replaces the planned `httpx`, because Starlette's test client deprecates `httpx` and asks for `httpx2`. It is only used in tests.
