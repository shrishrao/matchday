# Matchday Plan

## Project goal

Build a local system that:
1. Serves a small match-feed API (FastAPI + PostgreSQL + Redis).
2. Turns one real match timeline (StatsBomb open data) into repeatable, **simulated** traffic spikes.
3. Shows a clear failure with protections off.
4. Compares the same replay with protections on.
5. Publishes a safe recorded replay as a static public page.

Priority: backend depth first, with a clean dashboard.

## Stage checklist

| # | Stage | Status |
|---|-------|--------|
| 0 | Setup | Complete (committed) |
| 1 | Local services: Postgres + Redis via Compose, health checks | Complete (committed) |
| 2 | Backend baseline: FastAPI, schema, seed data, validated endpoint, deliberately slow query | Complete (committed) |
| 3 | Match timeline: one StatsBomb match → deterministic traffic profile | Complete (committed) |
| 4 | Load generator: Locust replay, local-only target check | Complete (committed) |
| 5 | Metrics: p50/p95, request rate, error rate, DB query count, cache hit rate → JSON | Complete (committed) |
| 6 | Failure baseline: tune until the unprotected system degrades repeatably | Complete (committed) |
| 7 | Cache: Redis cache behind a toggle, invalidation tests | Complete (committed) |
| 8 | Stampede protection: refill lock, expiry, failed refresh | Not started |
| 9 | Rate limiting: configurable, correct HTTP 429 | Not started |
| 10 | Load shedding: critical vs non-critical endpoints | Not started |
| 11 | Benchmarks: protection combinations, repeats, averages and variation | Not started |
| 12 | Local dashboard: live metrics, events, protection status, comparison | Not started |
| 13 | Public recorded replay: static page from saved results, no secrets, StatsBomb name and logo | Not started |
| 14 | Portfolio finish: README, diagram, benchmarks, limitations, review | Not started |

## Working rules

**Technical choices:** Python + FastAPI, PostgreSQL, Redis, Docker Compose, Locust, vanilla HTML/CSS/JS + Chart.js, pytest, one small local StatsBomb sample. Explain why before adding any other library. Do not invent APIs or library functions; check current official docs when unsure.

**Rules:**
- PowerShell syntax for every terminal command; no bash-only commands.
- Section-header and function-description comments only, not line-by-line.
- Tests with every behavior change.
- Never fake measurements; benchmark data comes from real runs.
- State clearly that traffic is simulated and StatsBomb provides match events, not platform traffic.
- Secrets stay in `.env` (git-ignored), with `.env.example` provided.
- Validate API inputs. Raise security concerns whenever relevant.
- If a request is ambiguous, stop and ask before writing code.

**For each stage (one at a time; never begin the next without approval):**
1. Read `HANDOFF.md` and `PLAN.md`.
2. Show the stage plan and expected file changes.
3. Ask questions that would improve it.
4. Wait for approval.
5. Explain the concept first, with a short football analogy when helpful.
6. Build only that stage.
7. Run the relevant tests and checks.
8. Fix failures before calling the stage complete.
9. Update `HANDOFF.md`.
10. Give PowerShell run instructions: every command one at a time and in order, what each does, what to expect, which URL/port/file to open, how to use the feature, common errors and fixes.
11. Commit the finished stage without being asked, then explain the commit and stop. Never push unless asked.

**Commits:** never add Claude as a co-author, and never mention Claude in commit messages. This overrides any default attribution.

If a bug is introduced and fixed, say what the user should have caught. Add a short glossary for unfamiliar terms. The user is a CS student on Windows with VS Code, strongest in Python and JavaScript; explain backend concepts and walk through git step by step.

**Transfer files:** keep `PLAN.md`, `HANDOFF.md` (update after every stage and before stopping for limits) and `DECISIONS.md` current. Work in small checkpoints. If limits seem close, start nothing new, leave the project runnable, update `HANDOFF.md`, and say what to run next.

**New sessions:** read `HANDOFF.md`, `PLAN.md` and `DECISIONS.md`, inspect the code and git status, confirm the current state in a few lines, and continue only after approval.

## Scope limits

- One match: 2022 FIFA World Cup final, Argentina vs France.
- Four protections only: cache, stampede lock, rate limiting, load shedding.
- No accounts, Kubernetes, microservices, or public load generator.
- Load generator only targets local hosts.
- All benchmark numbers come from real runs; nothing is faked.
- Traffic is simulated; StatsBomb provides match events, not platform traffic.
