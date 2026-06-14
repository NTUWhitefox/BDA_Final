#!/usr/bin/env python3
"""Collect game data from live APIs into data/raw/games_raw.csv.

Usage (run on a machine with open internet — the course sandbox blocks Steam):
    # Indie-weighted bulk collection (the realistic dataset for our wedge):
    python scripts/01_collect.py --source steamspy --indie --pages 10 --limit 4000

    # Quick demo seeds:
    python scripts/01_collect.py --source steamspy --top2weeks            # ~100 games
    python scripts/01_collect.py --source steamspy --pages 2 --limit 500  # slice of 'all'
    python scripts/01_collect.py --source steam --appids 1145360 646570 367520

IMPORTANT: SteamSpy's 'all' and 'top100in2weeks' endpoints do NOT return user
tags — only the per-app 'appdetails' endpoint does. So for the SteamSpy source we
first list candidate appids, then ENRICH each one with a per-app call to fetch its
tags (on by default). Without tags the recommender has nothing to work with.

The '--indie' flag filters the cheap bulk 'all' records (owners + review counts)
BEFORE the expensive per-app enrichment, so we only spend requests on the indie
long tail rather than the AAA blockbusters that 'most played' surfaces.

Robustness (PLAN.md section 5): the collection checkpoints to disk every
--checkpoint games and RESUMES by skipping appids already in the output file, so a
~90-minute run survives a dropped connection or a wiped /tmp2 without starting over.

Without network access this script is unnecessary: the pipeline already runs on
the bundled curated seed (data/sample/games_sample.csv).
"""
import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bda.collect import steam_store, steamspy          # noqa: E402
from bda.collect.load_sample import CANONICAL_COLS     # noqa: E402
from bda.config import RAW_CSV, STEAMSPY_DELAY_S        # noqa: E402


def _already_collected() -> set:
    """Appids already in the output CSV, so a resumed run skips them."""
    if not Path(RAW_CSV).exists() or Path(RAW_CSV).stat().st_size == 0:
        return set()
    try:
        return set(pd.read_csv(RAW_CSV)["appid"].astype("int64").tolist())
    except Exception:
        return set()


def _checkpoint(rows: list, append: bool) -> None:
    """Flush collected rows to the CSV (append after the first checkpoint)."""
    if not rows:
        return
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=CANONICAL_COLS)
    df.to_csv(RAW_CSV, mode="a" if append else "w",
              header=not append, index=False)


def _candidate_appids(args) -> list[int]:
    """Appids to enrich. In --indie mode we filter the bulk 'all' records by
    owners/review count first, so enrichment is spent only on the indie wedge."""
    if args.top2weeks:
        return steamspy.list_appids(top2weeks=True)
    if args.indie:
        kept = []
        for rec in steamspy.iter_all(max_pages=args.pages):
            if steamspy.is_indie_candidate(rec, max_owners=args.max_owners,
                                           max_reviews=args.max_reviews):
                appid = int(rec.get("appid", 0))
                if appid > 0:
                    kept.append(appid)
        print(f"Indie filter kept {len(kept)} candidates "
              f"(owners < {args.max_owners:,}, reviews < {args.max_reviews:,})")
        return kept
    return steamspy.list_appids(max_pages=args.pages)


def collect_steamspy(args) -> int:
    appids = _candidate_appids(args)
    if args.limit:
        appids = appids[: args.limit]

    seen = _already_collected()
    resuming = bool(seen)
    todo = [a for a in appids if a not in seen]
    print(f"{len(appids)} candidates; {len(seen)} already collected; "
          f"enriching {len(todo)} new appids with tags...")

    buffer, kept, skipped = [], 0, 0
    # On resume we append; otherwise the first checkpoint truncates the file.
    appended = resuming
    for n, appid in enumerate(todo, 1):
        try:
            rec = steamspy.fetch_app(appid)             # appdetails -> includes tags
        except Exception as e:                          # noqa: BLE001
            print(f"  [{n}/{len(todo)}] {appid}: fetch failed ({e})")
            skipped += 1
            continue
        norm = steamspy.normalize(rec)
        if norm["tags"]:
            buffer.append(norm)
            kept += 1
        else:
            skipped += 1
        time.sleep(STEAMSPY_DELAY_S)

        if len(buffer) >= args.checkpoint:
            _checkpoint(buffer, append=appended)
            appended = True
            print(f"  ...checkpoint: {n}/{len(todo)} processed "
                  f"(kept {kept}, skipped {skipped})")
            buffer = []

    _checkpoint(buffer, append=appended)                # final flush
    print(f"Enrichment done: {kept} new games with tags, {skipped} skipped.")
    return kept


def collect_steam(args) -> int:
    rows = []
    for appid in args.appids or []:
        details = steam_store.fetch_appdetails(appid)
        if not details:
            print(f"  skip {appid}: no storefront data")
            continue
        summary = steam_store.fetch_review_summary(appid)
        rows.append(steam_store.normalize(appid, details, summary))
    _checkpoint(rows, append=bool(_already_collected()))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["steamspy", "steam"], default="steamspy")
    ap.add_argument("--pages", type=int, default=1, help="SteamSpy 'all' pages (~1000 ids each)")
    ap.add_argument("--top2weeks", action="store_true", help="seed from SteamSpy top-100 instead of 'all'")
    ap.add_argument("--indie", action="store_true",
                    help="filter 'all' to the indie wedge before enrichment")
    ap.add_argument("--max-owners", type=int, default=2_000_000, dest="max_owners",
                    help="indie filter: drop games with >= this owner lower-bound")
    ap.add_argument("--max-reviews", type=int, default=100_000, dest="max_reviews",
                    help="indie filter: drop games with >= this many reviews")
    ap.add_argument("--limit", type=int, default=200, help="cap number of apps to enrich")
    ap.add_argument("--checkpoint", type=int, default=50,
                    help="flush to CSV every N enriched games (crash safety)")
    ap.add_argument("--appids", type=int, nargs="*", help="explicit app ids (steam source)")
    args = ap.parse_args()

    n = collect_steamspy(args) if args.source == "steamspy" else collect_steam(args)

    total = len(_already_collected())
    if total == 0:
        print("WARNING: no rows with tags were collected. The build will fall back "
              "to the bundled seed. Re-run with enrichment enabled (default) and "
              "network access to Steam/SteamSpy.")
    print(f"Added {n} games this run -> {RAW_CSV} (now {total} total). "
          f"Next: python scripts/02_build.py")


if __name__ == "__main__":
    main()
