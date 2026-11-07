# Failure baseline (Stage 6)

> Traffic is simulated. StatsBomb provides the match events, not platform traffic. All numbers were measured on one machine (16 logical CPUs, about 24 GB RAM, Windows 11, Docker Desktop), with the load generator on the same computer as the API. They are not a prediction for any other setup.

## Result

With **no protections**, a full 180-second replay at **15 base users (peak 120)** degraded in **3 of 3 runs**.

| Run | Requests/s | Feed p95 | Error rate | Most requests waiting for a connection |
|---|---|---|---|---|
| 1 | 18.72 | 10,011 ms | 11.15% | 84 |
| 2 | 22.40 | 10,002 ms | 8.09% | 68 |
| 3 | 17.35 | 10,033 ms | 14.35% | 67 |
| **Mean (stdev)** | **19.49 (2.61)** | **10,015 ms (16)** | **11.20% (3.13 points)** | |

At 5 base users, the Stage 5 full replay had a feed p95 of about 44 ms and no errors.

**Reading the feed p95:** about 10,000 ms is the fans' 10-second request timeout. At least 5% of feed requests hit it, so the real wait was even longer. The tight spread of the p95 comes from that limit, not from steady behaviour.

**Recovery:** 0.0 s in all three full runs. The full replay ends with quieter post-match traffic, so the backlog clears before the replay finishes. In the 30-second sweep at 20 base users, which ends on a spike, recovery took 7.0 s.

## Criteria (fixed before tuning; see DECISIONS.md D33)

A run is degraded if the feed p95 is at least 500 ms, or at least 1% of requests fail. The failure counts as repeatable when 3 full replays all degrade.

## How the level was chosen (`sweep.json`, 30-second replays)

| Base users | Peak | Requests/s | Feed p95 | Errors | Verdict |
|---|---|---|---|---|---|
| 5 | 40 | 13.73 | 103 ms | 0% | healthy |
| 10 | 80 | 25.57 | 580 ms | 0% | only just degraded |
| 15 | 120 | 18.03 | 10,090 ms | 26.25% | degraded |
| 20 | 160 | 17.10 | 10,113 ms | 61.21% | degraded |

10 users only just crossed the threshold, so it might not degrade every time. 15 users fails clearly. Beyond 10 users the request rate **falls**: the system completes less work while being asked for more.

## Why it fails

Each step below leads to the next:

1. **A goal triggers a spike.** The user count rises up to 8 times, and about 1 in 10 requests is the deliberately slow `/stats` query.
2. **The slow queries pile up.** Each one sorts 1,000,000 rows and spills to disk. On its own it takes about 1 s, but several running at once compete for the database, and its median rose to about 6 s in the sweep.
3. **They take every connection.** The pool has 10 connections. Slow queries hold them, so even the fast `/feed` request has to queue. Up to 84 requests were waiting for a connection at once.
4. **The queue turns into failures.** A request waiting more than 5 s for a connection gets a 503 (hundreds per run). A fan waiting more than 10 s gives up, and the server keeps working on that request anyway.
5. **Throughput collapses.** Fans wait for each reply, so slow replies mean fewer requests are completed per second.

This is **head-of-line blocking**: cheap requests stuck behind expensive ones. Each protection that follows targets one part of this chain:
- **Cache (Stage 7):** stops repeating the slow query.
- **Stampede lock (Stage 8):** stops many requests refilling the same cache entry at once.
- **Rate limiting (Stage 9):** caps how fast requests can arrive.
- **Load shedding (Stage 10):** protects `/feed` by turning away non-critical work when overloaded.

## Files

- `failure_baseline.json`: the settings, criteria, the three run evaluations and their spread.
- `runs/`: the three complete run results, including per-second rows.
- `sweep.json`: the load sweep used to choose the level.

## Reproduce

```powershell
python -m scripts.failure_baseline sweep --base-users 5 10 15 20
python -m scripts.failure_baseline confirm --base-users 15
```
