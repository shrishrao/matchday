# Handoff

## Current stage and status
**Stage 2: Backend baseline.** Complete and committed. Stage 3 has not started and needs approval.

## Finished and verified
**Stages 0 and 1**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, healthy, bound to `127.0.0.1`.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 2**
- FastAPI app with `/health`, `/matches/{id}`, `/matches/{id}/feed` and `/matches/{id}/stats`. Live server tested on `127.0.0.1:8000`.
- Seed data: 1 placeholder match (labelled `data_source: placeholder`), 7 placeholder events, 1,000,000 generated fan reactions.
- Two seed loads of the real database gave the same md5 fingerprint.
- Stopping Postgres gives a 503 with no internal details. After it restarts, the next requests succeed.

## Measurements (informal, one request at a time; not benchmarks)
- `/feed`: about 6 ms. `/stats`: about 700–800 ms over 12 requests.
- `EXPLAIN ANALYZE` on `/stats`: Seq Scan of all 1,000,000 rows, external merge sort spilling about 25 MB to disk, one run at 1,113 ms execution time. Run `python -m scripts.explain_slow_query` to see a current plan.

## Files changed in Stage 2
Added: `app/__init__.py`, `app/config.py`, `app/db.py`, `app/main.py`, `app/queries.py`, `app/schema.sql`, `app/schemas.py`, `scripts/seed.py`, `scripts/explain_slow_query.py`, `tests/conftest.py`, `tests/test_api.py`, `tests/test_seed.py`.
Changed: `requirements.txt`, `.env.example`, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.
Removed: `app/.gitkeep`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
python -m scripts.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m scripts.explain_slow_query
python -m pytest -v
docker compose down
```
Run `python -m scripts.*` from the project root. Interactive docs are at http://127.0.0.1:8000/docs while the server runs.

## Test results
`python -m pytest -q`: 84 passed in 38.61s, no warnings. Docker services must be running. Tests use a separate `matchday_test` database.

## Known problems
- While Postgres is down, each request waits up to 5 seconds (the pool timeout) before its 503.
- `.venv\Scripts\python.exe` can start a child process, so stopping a server by its launcher's process ID may not stop it right away. Use Ctrl+C in the server's terminal.
- Claude's own shell may not have `docker` on PATH until the app restarts.

## Decisions
See DECISIONS.md D1–D15.

## Exact next step
Show the Stage 3 plan (import the real StatsBomb match into a small local sample, build a deterministic traffic profile) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
