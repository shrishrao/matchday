"""Build the replay timeline from the sample and profile. Run with: python -m scripts.build_timeline"""

import sys

from app.timeline import (
    TIMELINE_PATH,
    build_timeline,
    fingerprint,
    load_profile,
    load_sample,
    serialize,
)


# ===== Command line =====
def main() -> int:
    """Write the timeline file and print a summary of it."""
    timeline = build_timeline(load_sample(), load_profile())
    TIMELINE_PATH.write_text(serialize(timeline), encoding="utf-8", newline="\n")
    peak = max(point["multiplier"] for point in timeline["points"])
    print(f"Wrote {TIMELINE_PATH}")
    print(f"Replay: {timeline['replay_seconds']} seconds, {len(timeline['moments'])} moments, peak {peak}x")
    print(f"Fingerprint: {fingerprint(timeline)}")
    print("Traffic is simulated. StatsBomb provides match events, not platform traffic.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
