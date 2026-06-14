#!/usr/bin/env python3
"""Incrementally add newly released games, then rebuild the index.

Intended to run on a schedule (cron, or the Cowork 'schedule' skill) so the
discovery graph never falls behind new releases:

    python scripts/04_refresh.py --max-new 200

Requires open network (Steam/SteamSpy). See PLAN.md section 5.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bda.collect.newreleases import collect_new   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new", type=int, default=200)
    args = ap.parse_args()
    new_df = collect_new(max_new=args.max_new)
    print(f"Added {len(new_df)} newly released games. Now run: python scripts/02_build.py")


if __name__ == "__main__":
    main()
