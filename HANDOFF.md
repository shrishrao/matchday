# Handoff

## Current stage and status
**Stage 3: Match timeline.** Complete and committed. Stage 4 has not started and needs approval.

## Finished and verified
**Earlier stages**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, healthy, bound to `127.0.0.1`.
- FastAPI app with `/health`, `/matches/{id}`, `/matches/{id}/feed` and `/matches/{id}/stats`. It recovers after a Postgres restart.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 3**
- Real match imported: StatsBomb 3869685, Argentina 3–3 France, 2022 World Cup final. The sample has 24 events (10 period markers, 6 goals, 8 shootout kicks) in 5.7 KB, from pinned StatsBomb commit `4b73468`.
- Importing twice gives identical bytes.
- `data/timeline_3869685.json`: 180 seconds, 19 moments, peak 8.0× (at the cap). Fingerprint `2ada46e3ea75793636f1add8dea6b8ca4b06bb0429ea11572f12a4d62daef733`.
- Building twice gives identical bytes, and separate processes with different `PYTHONHASHSEED` give the same fingerprint.
- The database and API now use the real match. `/feed` is in true order across overlapping minutes and uses `after_seconds`.
- Fan reactions are still generated, weighted toward the real goal and shootout minutes.

## Measurements (informal, one request at a time; not benchmarks)
- `/feed`: about 8–31 ms over 6 requests. `/stats`: about 880–1,440 ms over 6 requests. `EXPLAIN ANALYZE`: 1,057 ms execution, Seq Scan, external merge sort using about 25 MB of disk.
- These are not comparable with Stage 2, because the data shape changed.

## Files changed in Stage 3
Added: `app/timeline.py`, `data/match_3869685_sample.json`, `data/traffic_profile.json`, `data/timeline_3869685.json`, `scripts/import_statsbomb.py`, `scripts/build_timeline.py`, `tests/test_import.py`, `tests/test_timeline.py`.
Changed: `app/main.py`, `app/queries.py`, `app/schema.sql`, `app/schemas.py`, `scripts/seed.py`, `tests/test_api.py`, `tests/test_seed.py`, `README.md`, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.
Removed: `data/.gitkeep`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
python -m scripts.build_timeline
python -m scripts.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m pytest -q
docker compose down
```
`python -m scripts.import_statsbomb` only needs rerunning to regenerate the committed sample, and needs internet access.

## Test results
`python -m pytest -q`: 120 passed in 37.52s, no warnings. Docker services must be running. Tests use a separate `matchday_test` database.

## Known problems
- The 8 shootout kicks fall within about 6 replay seconds, so they merge into one surge at the 8× cap. This is a side effect of compressing the match to 3 minutes (D17).
- While Postgres is down, each request waits up to 5 seconds before its 503.
- `.venv\Scripts\python.exe` can start a child process, so stopping a server by its launcher's process ID may not stop it. Use Ctrl+C in the server's terminal.
- Claude's own shell may not have `docker` on PATH until the app restarts.

## Decisions
See DECISIONS.md D1–D21.

## Exact next step
Show the Stage 4 plan (Locust replay driven by the timeline, local-only target check, one documented command) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
