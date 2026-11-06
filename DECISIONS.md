# Decisions

Each entry: decision, alternatives considered, and tradeoffs.

## D1: Project lives at `C:\dev\matchday`, not in OneDrive (Stage 0)
- **Decision:** keep the repo outside OneDrive.
- **Alternatives:** the original `Desktop\Shrish\Fun\Matchday` folder (synced by OneDrive).
- **Why:** OneDrive syncing locks and re-uploads files while `.venv`, git and result files change rapidly. That causes "file in use" errors and slowdowns. Git plus GitHub is the backup instead.

## D2: Python 3.13 (Stage 0)
- **Decision:** create the virtual environment with Python 3.13.7, which is already installed.
- **Alternatives:** 3.10 (the default on PATH; past end of security support as of Oct 2026), 3.14 (newest; some compiled packages may lag behind), 3.12 (would need a new install).
- **Why:** 3.13 is mature and supported, and needs no download.

## D3: `venv` + `requirements.txt` for dependencies (Stage 0)
- **Decision:** use the standard library `venv` and pinned `requirements.txt` files.
- **Alternatives:** `uv`, Poetry.
- **Why:** nothing extra to install or learn; pinned versions keep runs reproducible. Tradeoff: slower installs, no automatic lock file.

## D4: Match = 2022 World Cup final, Argentina vs France (Stage 0)
- **Decision:** use this match from StatsBomb open data.
- **Why:** 6 goals in normal and extra time, plus a penalty shootout, give many distinct, explainable spikes.
- **Tradeoff:** the full event file is large; Stage 3 stores only a small extracted sample.

## D5: Line endings normalized to LF via `.gitattributes` (Stage 0)
- **Why:** files are edited on Windows but run inside Linux containers. LF in git avoids noisy diffs and broken shell scripts in containers.

## D6: Default git branch is `main` (Stage 0)
- **Why:** matches the current GitHub default.

## D7: Pin exact images: `postgres:18.6-alpine`, `redis:8.10.3-alpine` (Stage 1)
- **Alternatives:** `latest`, or major-only tags such as `18-alpine`.
- **Why:** a silent image update could change benchmark results between runs. Alpine images are smaller.
- **Tradeoff:** security patches arrive only when we bump the tag by hand. Postgres 18 also mounts its volume at `/var/lib/postgresql`, not the older `/var/lib/postgresql/data`.

## D8: Local-only ports, and passwords on both services (Stage 1)
- **Alternative:** Compose's default port publishing, which listens on all network interfaces, and no password on Redis.
- **Why:** binding to `127.0.0.1` keeps other devices on the network out. The Redis password adds a second layer.
- **Tradeoff:** a little more setup in `.env`.

## D9: Redis saves nothing to disk (Stage 1)
- **Alternative:** Redis snapshots or append-only persistence.
- **Why:** Redis is only a cache here and Postgres is the source of truth. Starting empty also keeps benchmark runs comparable.
- **Tradeoff:** every restart begins with an empty cache.

## D10: Integration tests fail when services are down, rather than skip (Stage 1)
- **Alternative:** skip them automatically.
- **Why:** a skipped test can look like a pass and hide a broken setup.
- **Tradeoff:** services must be running for a full test pass.
