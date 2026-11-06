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

## D16: A continuous "played" clock, and `after_seconds` on the feed (Stage 3)
- **Decision:** add `period` and `clock_seconds` to events, sort by them, and replace `after_minute` with `after_seconds`.
- **Alternative:** keep sorting by StatsBomb's minute.
- **Why:** StatsBomb's minutes overlap. The first half runs to 52:34 while the second half starts at 45:00, so sorting by minute gives the wrong order.
- **Tradeoff:** a change to a Stage 2 endpoint. Nothing depended on it yet. The clock excludes breaks, so it holds only real data.

## D17: Three-minute replay, with all assumptions in one file (Stage 3)
- **Decision:** `data/traffic_profile.json` holds the replay length, spike sizes, break lengths and post-match time. One match second maps to about 1/64 of a replay second.
- **Alternative:** a 5-minute replay, or real-time.
- **Why:** 16 combinations × 3 repeats takes about 2.4 hours at 3 minutes and 4 hours at 5.
- **Tradeoff:** the 8 shootout kicks fall within about 6 replay seconds, so they merge into one surge and hit the 8× cap.

## D18: Load as relative multipliers, with linear fades (Stage 3)
- **Decision:** the timeline gives one multiplier per second. Overlapping spikes add up, to a cap of 8×. Stage 6 sets real user numbers.
- **Alternatives:** user counts now, or exponential decay.
- **Why:** the breaking point on this machine is not known yet. Linear fades are simple to explain.
- **Tradeoff:** spike shapes are assumptions, not measurements. No real traffic data backs them.

## D19: Pin the data source and commit a small sample (Stage 3)
- **Decision:** import from StatsBomb commit `4b73468` and commit a 24-event, 5.7 KB sample with the source file's SHA-256.
- **Alternative:** download at run time from `master`.
- **Why:** an upstream change cannot alter results, and no network is needed to run the project.
- **Tradeoff:** the sample is a small redistribution of StatsBomb data, so its attribution terms apply.

## D20: Store the match date only, not kick-off time (Stage 3)
- **Decision:** replace the placeholder `kickoff_at` with `match_date`.
- **Why:** StatsBomb's `kick_off` value (17:00:00.000) has no timezone, so storing it as an exact moment would imply precision the data does not give.

## D21: Seeding drops and recreates the tables (Stage 3)
- **Alternative:** a migration tool such as Alembic.
- **Why:** all data can be regenerated from committed files and a fixed seed, so a migration tool adds nothing yet. Seeding refuses non-local hosts.
- **Tradeoff:** any manual changes to the database are lost when seeding.
