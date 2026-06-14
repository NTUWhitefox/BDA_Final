#!/usr/bin/env python3
"""Command-line demo of the discovery queries.

    python scripts/03_query.py --appid 1145360       # Hades
    python scripts/03_query.py --name "Slay"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bda.collect.load_sample import load_games          # noqa: E402
from bda.process.engine import RecommenderEngine        # noqa: E402


def show(title, hits):
    print(f"\n{title}")
    for h in hits:
        print(f"  [{h.niche}] {h.name:<32} sim={h.score:<7} (appid {h.appid})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--appid", type=int)
    ap.add_argument("--name", type=str)
    args = ap.parse_args()

    games, source = load_games()
    engine = RecommenderEngine(games)
    print(f"Loaded {len(games)} games from {source}")

    appid = args.appid
    if appid is None and args.name:
        hits = engine.search(args.name, limit=1)
        if not hits:
            print(f"No game matches '{args.name}'")
            return
        appid = hits[0].appid
    if appid is None:
        print("Provide --appid or --name")
        return

    base = engine.games[engine.games["appid"] == appid]
    if base.empty:
        print(f"appid {appid} not in dataset")
        return
    print(f"\n=== Discovery report for: {base.iloc[0]['name']} (appid {appid}) ===")

    show("Players — games like this:", engine.similar(appid, k=5))
    show("Developers — direct competitors (same niche):", engine.competitors(appid, k=5))

    prof = engine.niche_profile(appid)
    print(f"\nNiche #{prof['niche_id']} ({prof['niche_size']} games)")
    print(f"  Defining tags: {', '.join(prof['defining_tags'])}")
    print("  Audience hubs (where this audience concentrates):")
    for h in prof["audience_hubs"]:
        print(f"    - {h['name']} (PageRank {h['score']})")
    print(f"  Positioning gaps (under-used tags to differentiate): "
          f"{', '.join(engine.niche_gaps(appid))}")


if __name__ == "__main__":
    main()
