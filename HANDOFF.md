# Handoff

## Current stage and status
**Stage 4: Load generator.** Complete and committed. Stage 5 has not started and needs approval.

GitHub: https://github.com/shrishrao/matchday (private). Stages 0 to 3 were pushed. Commits are pushed only when asked, so check `git status` to see whether later commits are local only.

## Finished and verified
**Earlier stages**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, healthy, bound to `127.0.0.1`.
- FastAPI app with `/health`, `/matches/{id}`, `/matches/{id}/feed` and `/matches/{id}/stats`, using the real 2022 final (StatsBomb match 3869685).
- Deterministic 180-second timeline with a stored fingerprint.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 4**
- `python -m scripts.run_replay --short` runs a 30-second replay. Without `--short`, it runs 180 seconds.
- Real replays against the seeded database: the user count was on target for 100% of seconds in both the short and full runs.
- Non-local targets are refused by both the command and Locust itself. A test confirms a direct Locust run sends 0 requests to a non-allowed address.
- Locust's web page and distributed modes are refused.

## Measurements (one informal full replay at 5 base users; not a benchmark)
- 2,392 requests, 0 failures, 13.25 requests per second, peak 40 users.
- Median response: `/feed` 7 ms, `/matches/[id]` 6 ms, `/stats` 890 ms. Overall p95 870 ms.
- The system did not fail at this load. Stage 6 increases it.

## Files changed in Stage 4
Added: `loadgen/__init__.py`, `loadgen/safety.py`, `loadgen/schedule.py`, `loadgen/locustfile.py`, `scripts/run_replay.py`, `tests/test_safety.py`, `tests/test_replay_shape.py`.
Changed: `requirements.txt`, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.
Removed: `loadgen/.gitkeep`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
python -m scripts.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m scripts.run_replay --short
python -m scripts.run_replay
python -m pytest -q
docker compose down
```
Run the API in one terminal and the replay in another. Options: `--base-users`, `--replay-seconds`, `--host` (local only).

## Test results
`python -m pytest -q`: 202 passed in 67.02s, no warnings. Docker services must be running. Tests use a separate `matchday_test` database, and one test runs a real 12-second replay on port 8765.

## Known problems
- Locust and the API share this computer's CPU, so heavy load can slow Locust itself and affect measurements.
- Simulated fans wait for each response, so a slow server receives fewer requests (D25).
- `.venv\Scripts\python.exe` can start a child process, so stopping a server by its launcher's process ID may not stop it. Use Ctrl+C in the server's terminal.
- Claude's own shell may not have `docker` on PATH until the app restarts.

## Decisions
See DECISIONS.md D1–D26.

## Exact next step
Show the Stage 5 plan (record p50 and p95 latency, request rate, error rate, database query count and cache hit rate, and save each run as structured JSON) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
