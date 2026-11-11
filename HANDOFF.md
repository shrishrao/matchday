# Handoff

## Current stage and status
**Stage 7: Cache.** Complete and committed. Stage 8 has not started and needs approval.

GitHub: https://github.com/shrishrao/matchday (private). Commits are pushed only when asked, so check `git status -sb` to see whether `main` is ahead of `origin/main`.

## Finished and verified
**Earlier stages**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, bound to `127.0.0.1`. Redis is capped at 64 MB with `allkeys-lru`.
- FastAPI app using the real 2022 final (StatsBomb match 3869685), with a deterministic 180-second timeline.
- Local-only Locust replay, which saves measured results. Failure criteria (D33): feed p95 of at least 500 ms, or at least 1% errors.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 7**
- Redis cache-aside for `/matches/{id}`, `/feed` and `/stats`, turned on with `CACHE_ENABLED=true` (off by default). TTLs: match 5 s, feed 2 s, stats 10 s. Each response has an `X-Cache` header: HIT, MISS, OFF or UNAVAILABLE.
- Invalidation: TTL expiry, `invalidate_match()`, `clear()`, and seeding clears the cache. 404s and invalid requests are never cached.
- If Redis fails, requests fall back to Postgres. redis-py's default 10 retries are turned off, which cut the wait with Redis down from about 10 s to 0.5 s.
- `/internal/metrics` reports cache hits, misses and errors, plus which protections are on. Result files take protections from the API and count cache numbers per run.
- **Bug found and fixed (D39):** routes borrowed connections through a FastAPI `yield` dependency, which starved the thread pool under load. This caused most of the Stage 6 collapse. Routes now borrow inside their own thread.
- **New unprotected baseline (D41):** 30 base users (`results/baseline_v2`). The Stage 6 files are kept unchanged, with a correction note.
- **Comparison (`results/cache`), 3 full replays per setting at 30 base users:**
  - Cache off degraded in 3 of 3 runs, cache on in 1 of 3.
  - Feed p95: 2,985 ms → 479 ms.
  - Requests per second: 48.8 → 78.7.
  - Database queries per request: 1.80 → 0.06.
  - Hit rate 96.6%.
  - Up to 30 requests still waited for a connection with the cache on, because of the stats stampede at each 10-second expiry. That is what Stage 8 targets.

## Files changed in Stage 7
Added: `app/cache.py`, `scripts/compare_cache.py`, `tests/test_cache.py`, `tests/test_compare_cache.py`, `results/baseline_v2/` (README, sweep), `results/cache/` (README, comparison, six run files, smoke test).
Changed: `app/config.py`, `app/db.py`, `app/main.py`, `app/metrics.py`, `app/schemas.py`, `docker-compose.yml`, `.env.example`, `loadgen/results.py`, `loadgen/degradation.py`, `scripts/run_replay.py`, `scripts/failure_baseline.py` (`--folder`), `scripts/seed.py`, `results/baseline/README.md`, tests, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
python -m scripts.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
$env:CACHE_ENABLED = "true"; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m scripts.run_replay --short --base-users 30
python -m scripts.compare_cache --base-users 30 --repeats 3
python -m scripts.failure_baseline sweep --base-users 15 20 30 40 --folder baseline_v2
python -m pytest -q
docker compose down
```
`compare_cache` starts its own API, so stop yours first. In a PowerShell window, `$env:CACHE_ENABLED` stays set until you close it or run `Remove-Item Env:CACHE_ENABLED`.

## Test results
`python -m pytest -q`: 342 passed in 106.96s. Docker services must be running.

## Known problems
- With the cache on, the stats entry stampedes every 10 seconds. This is expected until Stage 8.
- With Redis down, every request still waits for one Redis timeout (up to 0.5 s). There is no circuit breaker (D40).
- Within a TTL, changed data is served stale unless it is invalidated.
- Feed p95 under heavy overload can reach the 10-second request timeout, which understates the real wait.
- Locust and the API share this computer's CPU (D25). Run-to-run spread is large, as runs 5 and 6 of the comparison show.
- Claude's own shell may not have `docker` on PATH. Docker Desktop may need starting after a reboot.

## Decisions
See DECISIONS.md D1–D42.

## Exact next step
Show the Stage 8 plan (stampede protection: refill lock, expiry, failed refresh) and wait for approval. Compare at 30 base users against the cache-only results.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
