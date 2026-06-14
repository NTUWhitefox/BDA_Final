"""Loader that picks the best available dataset.

Priority:
  1. data/raw/games_raw.csv   -> produced by the live collectors (real, fresh)
  2. data/sample/games_sample.csv -> bundled curated real-game seed (offline)
  3. any *.csv dropped into data/sample/ (e.g. a Kaggle Steam dataset)

A live file that is empty or has no tagged rows is skipped, so a botched
collection falls back to the seed instead of crashing the pipeline.
"""
from __future__ import annotations

import pandas as pd

from ..config import RAW_CSV, SAMPLE_CSV, SAMPLE_DIR

CANONICAL_COLS = [
    "appid", "name", "developer", "tags", "genres",
    "owners", "price_usd", "positive", "negative", "release_year",
]

MIN_GAMES = 2  # below this, similarity/graph steps are meaningless


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for col in CANONICAL_COLS:
        if col not in df.columns:
            df[col] = ""
    df = df[CANONICAL_COLS].copy()
    df["appid"] = pd.to_numeric(df["appid"], errors="coerce").fillna(0).astype("int64")
    df["tags"] = df["tags"].fillna("").astype(str)
    df = df[df["tags"].str.strip() != ""]          # drop tagless rows
    df = df.drop_duplicates(subset="appid").reset_index(drop=True)
    return df


def _try_load(path) -> "pd.DataFrame | None":
    """Read + coerce a CSV, returning None if missing, empty, or too few tagged
    rows. Lets us skip a botched live collection and fall back to the next source."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        df = _coerce(pd.read_csv(path))
    except Exception:
        return None
    return df if len(df) >= MIN_GAMES else None


def load_games() -> "tuple[pd.DataFrame, str]":
    """Return (dataframe, source_label), preferring live data but gracefully
    falling back to the bundled seed if the live file is empty/unusable."""
    candidates = [(RAW_CSV, "live-collected"), (SAMPLE_CSV, "bundled seed")]
    candidates += [(c, "dropped-in dataset") for c in sorted(SAMPLE_DIR.glob("*.csv"))
                   if c != SAMPLE_CSV]
    for path, label in candidates:
        df = _try_load(path)
        if df is not None:
            return df, f"{label} ({path.name})"

    if RAW_CSV.exists():
        raise ValueError(
            f"{RAW_CSV.name} has no usable rows (every row had empty tags). "
            "SteamSpy's 'all'/'top100in2weeks' endpoints do NOT return tags - "
            "re-run collection with tag enrichment (on by default): "
            "`python scripts/01_collect.py --source steamspy --top2weeks`, "
            "or delete data/raw/games_raw.csv to use the bundled seed."
        )
    raise FileNotFoundError(
        "No dataset found. Run scripts/01_collect.py or keep data/sample/games_sample.csv."
    )
