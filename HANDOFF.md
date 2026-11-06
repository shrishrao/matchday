# Handoff

## Current stage and status
**Stage 1: Local services.** Built and verified. **Not committed:** the repo has no commits yet, including Stage 0. Stage 2 has not started and needs approval.

## Finished and verified
**Stage 0**
- Repo at `C:\dev\matchday`, branch `main`, git identity configured.
- Python 3.13.7 venv at `.venv`. WSL2 working.
- Docker Desktop 4.98.0 (Docker 29.9.2, Compose v5.6.1), official installer with verified signature.
- Machine: 16 logical CPUs, ~24 GB RAM.

**Stage 1**
- Postgres 18.6 and Redis 8.10.3 start through Compose and report `healthy`.
- Ports are bound to `127.0.0.1` only.
- `scripts/check_services.py` runs a real query on Postgres and a write/read/delete on Redis. It exits 0 when both pass.
- With Redis really stopped, the script reports FAIL and exits 1. After `down` and `up`, both are healthy again.
- `.env` holds random local passwords and is git-ignored. No untracked file git would add contains the real passwords.

## Files changed in Stage 1
Added: `docker-compose.yml`, `requirements.txt`, `pytest.ini`, `scripts/check_services.py`, `tests/test_check_services.py`, local `.env` (not tracked).
Changed: `.env.example` (added `REDIS_PASSWORD`), `PLAN.md`, `HANDOFF.md`, `DECISIONS.md`.
Removed: `scripts/.gitkeep`, `tests/.gitkeep`.

## Commands that work (PowerShell, from `C:\dev\matchday`)
```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait
docker compose ps
python scripts\check_services.py
python -m pytest -v
docker compose down
```

## Test results
`python -m pytest -v`: 23 passed in 33.44s (19 without services, 4 integration). Integration tests need the services running and fail if they are down.

## Known problems
- Repo has no commits. The user reported committing Stage 0, but `git log` shows none and no matching commit was found in the likely folders. Cause unknown.
- The test suite takes about 33 seconds, mostly connection attempts to closed ports on Windows.
- Claude's own shell may not have `docker` on PATH until the app restarts. The system PATH does include it.
- The `py` launcher is installed but not on PATH. Use the venv's `python`.

## Decisions
See DECISIONS.md D1–D10.

## Exact next step
1. User makes the Stage 0 and Stage 1 commits and confirms with `git log --oneline`.
2. Show the Stage 2 plan (FastAPI app, schema, seed data, validated match-feed endpoint, deliberately slow query) and wait for approval.

## Resume prompt
```
We're building Matchday in C:\dev\matchday. Read HANDOFF.md, PLAN.md and DECISIONS.md, inspect the code and git status, confirm the current state in a few lines, and wait for my approval before continuing. Follow the "Working rules" section of PLAN.md exactly.
```
