"""Merge multiple data sources into one canonical games table.

Lets the system combine SteamSpy (tags/owners), the Steam Storefront (genres,
reviews, release date) and IGDB (themes/franchises) - or any extra CSV in the
canonical schema - into a single deduplicated dataset keyed by appid.

Strategy: concatenate all sources, then for each appid keep the row with the
richest tag set, filling missing fields from the other sources. This is the
offline-testable core of the multi-source ingestion described in PLAN.md section 5.
"""
from __future__ import annotations

import pandas as pd

from .load_sample import CANONICAL_COLS, _coerce


def _richness(tags: str) -> int:
    return len(str(tags).split("|")) if str(tags).strip() else 0


def merge_sources(frames: list) -> pd.DataFrame:
    """Merge a list of DataFrames (each in canonical schema) by appid."""
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLS)
    combined = pd.concat([_coerce(f) for f in frames], ignore_index=True)

    merged_rows = []
    for appid, grp in combined.groupby("appid"):
        grp = grp.sort_values("tags", key=lambda s: s.map(_richness), ascending=False)
        base = grp.iloc[0].to_dict()
        # fill blank fields from other sources for the same appid
        for col in CANONICAL_COLS:
            if (base.get(col) in ("", 0, None)) or pd.isna(base.get(col)):
                for _, other in grp.iloc[1:].iterrows():
                    val = other[col]
                    if val not in ("", 0, None) and not pd.isna(val):
                        base[col] = val
                        break
        merged_rows.append(base)
    return pd.DataFrame(merged_rows, columns=CANONICAL_COLS).reset_index(drop=True)


def merge_csvs(paths: list) -> pd.DataFrame:
    return merge_sources([pd.read_csv(p) for p in paths])
