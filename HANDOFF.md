# Handoff

## Current stage and status
**Stage 5: Metrics.** Complete and committed. Stage 6 has not started and needs approval.

GitHub: https://github.com/shrishrao/matchday (private). Commits are pushed only when asked, so check `git status -sb` to see whether `main` is ahead of `origin/main`.

## Finished and verified
**Earlier stages**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, healthy, bound to `127.0.0.1`.
- FastAPI app using the real 2022 final (StatsBomb match 3869685), with a deterministic 180-second timeline.
- Local-only Locust replay: `python -m scripts.run_replay [--short]`.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 5**
- Every replay saves `results/runs/run_<UTC time>.json`, which git ignores. It records:
  - p50, p95, p99 and max latency, overall and per endpoint
  - request rate, and failures with error rate
  - database queries, in total and per request
  - cache hit rate: null, because there is no cache yet
  - one row per second: users asked for and actual, requests, failures, p50, p95, database queries
  - settings (including protections, all off) and the environment (git commit, CPUs, OS)
- The API exposes `/internal/metrics` with its query counter and cache status.
- Checked against Locust's own table: our p95 of 979.4 ms against its approximate 980 ms. Measured queries per request (1.81) match what the request mix predicts (1.8).
- Kept example: `results/examples/stage5_full_replay_5_base_users.json` (real run).

## Measurements (one full replay at 5 base users, peak 40; not yet a benchmark)
- 2,385 requests, 0 failures, 13.25 per second, p50 8.6 ms, p95 938.9 ms, 4,327 database queries (1.814 per request).
- The system is not under stress at this load. Stage 6 increases it.

## Files changed in Stage 5
Added: `app/metrics.py`, `loadgen/results.py`, `tests/test_results.py`, `results/examples/stage5_full_replay_5_base_users.json`.
Changed: `app/queries.py`, `app/main.py`, `app/schemas.py`, `loadgen/locustfile.py`, `loadgen/schedule.py`, `scripts/run_replay.py`, `tests/test_api.py`, `tests/test_replay_shape.py`, `.gitignore`, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.

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
Run the API in one terminal and replays in another. Restart the API after code changes, or the replay stops with a message about `/internal/metrics`.

## Test results
`python -m pytest -q`: 240 passed in 78.22s, no warnings. Docker services must be running. Tests use a separate `matchday_test` database. One test runs a real 12-second replay on port 8765.

## Known problems
- After a database restart, a pool full of dead connections can return about two 503s before recovering (D32).
- About once per full replay, a Locust tick skips a second, so that second has no row (D30).
- Locust and the API share this computer's CPU. Simulated fans wait for each response, so a slow server gets fewer requests (D25).
- `.venv\Scripts\python.exe` can start a child process, so use Ctrl+C in the server's terminal to stop it.
- Claude's own shell may not have `docker` on PATH until the app restarts.

## Decisions
See DECISIONS.md D1–D32.

## Exact next step
Show the Stage 6 plan (tune the traffic until the unprotected system visibly degrades on this machine, and save the settings and results) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
