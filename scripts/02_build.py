#!/usr/bin/env python3
"""Build the recommendation index and write artifacts for inspection.

    python scripts/02_build.py

Reads the best available dataset (live raw -> bundled seed), fits the engine,
and writes artifacts/games.csv (+ index_meta.json) summarising the niches found.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bda.collect.load_sample import load_games          # noqa: E402
from bda.config import ARTIFACTS_DIR, GAMES_CSV, META_JSON  # noqa: E402
from bda.process.engine import RecommenderEngine        # noqa: E402


def main() -> None:
    games, source = load_games()
    print(f"Loaded {len(games)} games from {source}")

    engine = RecommenderEngine(games)
    print(f"Tags: {len(engine.tags)} | niches (Louvain communities): {engine.n_niches}")

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    engine.games.to_csv(GAMES_CSV, index=False)

    # niche summary: id -> sample of member game names
    niches = {}
    for niche_id, grp in engine.games.groupby("niche"):
        niches[int(niche_id)] = grp["name"].head(6).tolist()

    META_JSON.write_text(json.dumps({
        "source": source,
        "n_games": int(len(games)),
        "n_tags": len(engine.tags),
        "n_niches": engine.n_niches,
        "niche_examples": niches,
    }, indent=2, ensure_ascii=False))
    print(f"Wrote {GAMES_CSV.name} and {META_JSON.name} to artifacts/")
    for nid, names in sorted(niches.items()):
        print(f"  niche {nid}: {', '.join(names)}")


if __name__ == "__main__":
    main()
