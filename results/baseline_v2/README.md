# Unprotected baseline after the Stage 7 fix

> Traffic is simulated. StatsBomb provides the match events, not platform traffic. Measured on one machine (16 logical CPUs, about 24 GB RAM, Windows 11, Docker Desktop), with the load generator on the same computer as the API.

## Why there is a second baseline

Stage 7 found that the Stage 6 collapse was largely **thread-pool starvation**, caused by the way routes borrowed database connections (DECISIONS.md D39). With that fixed, the unprotected API behaves differently. It still slows down under load, because slow `/stats` queries still hold every connection, but it no longer starts failing.

## Sweep (`sweep.json`, 30-second replays, cache off)

| Base users | Peak | Requests/s | Feed p95 | Errors | Verdict |
|---|---|---|---|---|---|
| 15 | 120 | 40.27 | 489 ms | 0% | healthy (just) |
| 20 | 160 | 50.00 | 1,131 ms | 0% | degraded |
| 30 | 240 | 62.17 | 1,632 ms | 0% | degraded |
| 40 | 320 | 65.77 | 3,958 ms | 0% | degraded |

Up to 30 requests waited for a connection at every level. That is 40 worker threads minus the 10 that hold connections. The request rate still rises with load, so this is a slowdown, not a collapse.

**Chosen level: 30 base users** (D41). It is clearly past the 500 ms threshold. The three cache-off runs in `results/cache/comparison.json` confirm it over full replays.

## Reproduce

Start the API with the cache off, then:

```powershell
python -m scripts.failure_baseline sweep --base-users 15 20 30 40 --folder baseline_v2
```
