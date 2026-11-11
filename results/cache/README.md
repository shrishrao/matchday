# Cache comparison (Stage 7)

> Traffic is simulated. StatsBomb provides the match events, not platform traffic. Measured on one machine (16 logical CPUs, about 24 GB RAM, Windows 11, Docker Desktop), with the load generator on the same computer as the API. These numbers describe this machine only.

## Setup

- Full 180-second replays at **30 base users (peak 240)**, the unprotected baseline from `results/baseline_v2` (DECISIONS.md D41).
- Runs alternated cache off and on, 3 each. The script started the API itself for every run and emptied the cache first (D42).
- Cache TTLs: match 5 s, feed 2 s, stats 10 s.
- Degradation criteria are unchanged from Stage 6 (D33): feed p95 of at least 500 ms, or at least 1% errors.

## Result

| | Cache off (mean, stdev) | Cache on (mean, stdev) | Change |
|---|---|---|---|
| Runs degraded | **3 of 3** | **1 of 3** | |
| Feed p95 | 2,985 ms (1,290) | 479 ms (513) | 6.2 times lower |
| Overall p95 | 3,271 ms (1,352) | 694 ms (837) | 4.7 times lower |
| Stats p95 | 4,395 ms (1,908) | 2,547 ms (2,057) | 1.7 times lower |
| Requests per second | 48.8 (7.7) | 78.7 (6.7) | 1.6 times more |
| Database queries per request | 1.80 | 0.062 | 29 times fewer |
| Cache hit rate | not measured | 96.6% (0.75 points) | |
| Error rate | 0.00% | 0.02% | both far below 1% |
| Most requests waiting for a connection | 30 | 30 | **no change** |

### Each run, in the order they ran

| Order | Cache | Feed p95 | Stats p95 | Requests/s | Hit rate | Degraded |
|---|---|---|---|---|---|---|
| 1 | off | 2,149 ms | 3,195 ms | 53.21 | not measured | yes |
| 2 | on | 161 ms | 1,090 ms | 83.03 | 97.3% | no |
| 3 | off | 2,337 ms | 3,394 ms | 53.32 | not measured | yes |
| 4 | on | 205 ms | 1,651 ms | 82.07 | 96.7% | no |
| 5 | off | 4,470 ms | 6,595 ms | 39.91 | not measured | yes |
| 6 | on | 1,071 ms | 4,901 ms | 71.01 | 95.8% | yes |

Runs 5 and 6 were both the worst of their setting. Something on this computer was slower during that stretch, and alternating the settings spread that slowdown across both rather than hiding it in one.

## What this shows

1. **The cache removes most of the database work.** 96–97% of requests were answered from Redis, so queries per request fell from 1.80 to 0.06, and the API handled 1.6 times as many requests.
2. **It does not remove the pile-up.** Up to 30 requests still waited for a connection in every cache-on run, as many as with the cache off. The reason is the **stampede**: every 10 seconds the stats entry expires, and every stats request that arrives before the first refill finishes misses and runs the slow query too. For a few seconds those queries hold every connection, and feed misses queue behind them. This is why the stats p95 stayed high (2.5 s) and why one cache-on run still crossed the threshold.
3. **Stage 8 (stampede lock) targets exactly this:** one request refills an expired entry while the others wait for it or get the old value.

## Files

- `comparison.json`: settings, all six evaluations, the summaries, the changes, and the Stage 6 baseline summary for reference.
- `runs/`: the six complete run results, including per-second rows.
- `comparison_30s.json`: a short smoke test from development (1 run per setting, 30-second replays), not used for the result above.

## Reproduce

Stop your own API first, because the script starts its own on port 8000:

```powershell
python -m scripts.compare_cache --base-users 30 --repeats 3
```
