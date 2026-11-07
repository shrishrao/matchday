# Handoff

## Current stage and status
**Stage 6: Failure baseline.** Complete and committed. Stage 7 has not started and needs approval.

GitHub: https://github.com/shrishrao/matchday (private). Commits are pushed only when asked, so check `git status -sb` to see whether `main` is ahead of `origin/main`.

## Finished and verified
**Earlier stages**
- Repo at `C:\dev\matchday`, branch `main`. Python 3.13.7 venv at `.venv`. Docker Desktop 4.98.0.
- Postgres 18.6 and Redis 8.10.3 run through Compose, healthy, bound to `127.0.0.1`.
- FastAPI app using the real 2022 final (StatsBomb match 3869685), with a deterministic 180-second timeline.
- Local-only Locust replay, which saves measured results to `results/runs` (git-ignored).
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 6**
- Failure criteria were fixed before tuning (D33): feed p95 of at least 500 ms, or at least 1% errors.
- Sweep (30-second replays): 5 users healthy, 10 only just degraded, 15 and 20 badly degraded. The request rate falls beyond 10 users.
- Baseline: **15 base users (peak 120), no protections, degraded in 3 of 3 full replays**. Mean feed p95 10,015 ms (capped by the 10-second request timeout), mean error rate 11.20% (stdev 3.13 points), mean 19.49 requests per second.
- The failure is explained in `results/baseline/README.md`: slow `/stats` queries hold all 10 pool connections, so fast `/feed` requests queue behind them (head-of-line blocking).
- Measurement fixes: in-flight requests are now recorded (D34), metrics stay readable under load (D35), recovery time is measured (D36), and the timeline check allows fans finishing their last request (D38).
- `/internal/metrics` now reports pool size, available connections, waiting requests and failed connection requests.

## Files changed in Stage 6
Added: `loadgen/degradation.py`, `scripts/failure_baseline.py`, `tests/test_degradation.py`, and in `results/baseline/`: `README.md`, `sweep.json`, `failure_baseline.json` and `runs/` (3 run files).
Changed: `app/main.py`, `app/schemas.py`, `loadgen/results.py`, `loadgen/schedule.py`, `loadgen/locustfile.py`, `scripts/run_replay.py`, `tests/test_api.py`, `tests/test_results.py`, `tests/test_replay_shape.py`, `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
python -m scripts.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m scripts.run_replay --short
python -m scripts.run_replay --base-users 15
python -m scripts.failure_baseline sweep --base-users 5 10 15 20
python -m scripts.failure_baseline confirm --base-users 15
python -m pytest -q
docker compose down
```
Run the API in one terminal and replays in another. Restart the API after code changes. A replay where requests fail exits with code 1, which is expected at 15 base users.

## Test results
`python -m pytest -q`: 274 passed in 79.09s, no warnings. Docker services must be running.

## Known problems
- The feed p95 under overload is capped by the 10-second request timeout, so it understates the real wait.
- The full replay ends on quiet post-match traffic, so measured recovery is 0 s. A replay ending on a spike would show recovery better.
- After a database restart, a full pool of dead connections can return about two 503s (D32).
- Locust and the API share this computer's CPU (D25).
- Claude's own shell may not have `docker` on PATH until the app restarts.

## Decisions
See DECISIONS.md D1–D38.

## Exact next step
Show the Stage 7 plan (Redis cache behind an on/off setting, invalidation tests, and the same replay compared with the cache on and off, using the Stage 6 baseline) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
