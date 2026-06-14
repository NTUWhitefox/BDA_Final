#!/usr/bin/env python3
"""Collect game data from live APIs into data/raw/games_raw.csv.

Usage (run on a machine with open internet — the course sandbox blocks Steam):
    python scripts/01_collect.py --source steamspy --top2weeks            # ~100 games
    python scripts/01_collect.py --source steamspy --pages 2 --limit 500  # slice of 'all'
    python scripts/01_collect.py --source steam --appids 1145360 646570 367520

IMPORTANT: SteamSpy's 'all' and 'top100in2weeks' endpoints do NOT return user
tags — only the per-app 'appdetails' endpoint does. So for the SteamSpy source we
first list candidate appids, then ENRICH each one with a per-app call to fetch its
tags (on by default). Without tags the recommender has nothing to work with, which
is why a non-enriched collection produced an empty, unusable file.

Without network access this script is unnecessary: the pipeline already runs on
the bundled curated seed (data/sample/games_sample.csv).
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bda.collect import steam_store, steamspy          # noqa: E402
from bda.config import RAW_CSV, STEAMSPY_DELAY_S        # noqa: E402
import time                                             # noqa: E402


def collect_steamspy(args) -> list[dict]:
    appids = steamspy.list_appids(max_pages=args.pages, top2weeks=args.top2weeks)
    if args.limit:
        appids = appids[: args.limit]
    print(f"Found {len(appids)} candidate appids; enriching with tags via appdetails...")

    rows, kept, skipped = [], 0, 0
    for n, appid in enumerate(appids, 1):
        if args.no_enrich:
            # not recommended — leaves tags empty; kept only for completeness
            rows.append(steamspy.normalize({"appid": appid}))
            continue
        try:
            rec = steamspy.fetch_app(appid)             # appdetails -> includes tags
        except Exception as e:                          # noqa: BLE001
            print(f"  [{n}/{len(appids)}] {appid}: fetch failed ({e})")
            skipped += 1
            continue
        norm = steamspy.normalize(rec)
        if norm["tags"]:
            rows.append(norm)
            kept += 1
        else:
            skipped += 1
        time.sleep(STEAMSPY_DELAY_S)
        if n % 25 == 0:
            print(f"  ...{n}/{len(appids)} processed (kept {kept}, skipped {skipped})")
    print(f"Enrichment done: {kept} games with tags, {skipped} skipped.")
    return rows


def collect_steam(args) -> list[dict]:
    rows = []
    for appid in args.appids or []:
        details = steam_store.fetch_appdetails(appid)
        if not details:
            print(f"  skip {appid}: no storefront data")
            continue
        summary = steam_store.fetch_review_summary(appid)
        rows.append(steam_store.normalize(appid, details, summary))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["steamspy", "steam"], default="steamspy")
    ap.add_argument("--pages", type=int, default=1, help="SteamSpy 'all' pages (~1000 ids each)")
    ap.add_argument("--top2weeks", action="store_true", help="seed from SteamSpy top-100 instead of 'all'")
    ap.add_argument("--limit", type=int, default=200, help="cap number of apps to enrich")
    ap.add_argument("--no-enrich", action="store_true", help="skip per-app tag enrichment (NOT recommended)")
    ap.add_argument("--appids", type=int, nargs="*", help="explicit app ids (steam source)")
    args = ap.parse_args()

    rows = collect_steamspy(args) if args.source == "steamspy" else collect_steam(args)

    df = pd.DataFrame(rows)
    tagged = int((df["tags"].astype(str).str.strip() != "").sum()) if len(df) else 0
    if tagged == 0:
        print("WARNING: no rows with tags were collected. The build will fall back "
              "to the bundled seed. Re-run with enrichment enabled (default) and "
              "network access to Steam/SteamSpy.")
    df.to_csv(RAW_CSV, index=False)
    print(f"Wrote {len(df)} games ({tagged} with tags) -> {RAW_CSV}")


if __name__ == "__main__":
    main()
