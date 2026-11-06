# Matchday

Matchday replays one football match as **simulated** traffic against a small backend. It shows the system failing under match-day spikes, then measures how each protection improves it.

> **Important:** the traffic is simulated. StatsBomb open data provides the match **events** (goals, breaks, full-time) that shape the traffic. It does not provide real platform traffic.

## Status

Work in progress. See [PLAN.md](PLAN.md) for stage status and [HANDOFF.md](HANDOFF.md) for the current state.

## Stack

Python 3.13 · FastAPI · PostgreSQL · Redis · Docker Compose · Locust · pytest · vanilla HTML/CSS/JS + Chart.js

## Protections measured

1. Redis cache
2. Cache-stampede lock
3. Rate limiting
4. Load shedding

## Data attribution

Match event data: [StatsBomb Open Data](https://github.com/statsbomb/open-data). Attribution is required by the StatsBomb open data licence.

## Setup

Coming in Stage 14. For now, see the run instructions in [HANDOFF.md](HANDOFF.md).
