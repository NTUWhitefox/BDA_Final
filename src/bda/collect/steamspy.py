"""Live collector for the SteamSpy API (unofficial, no API key required).

SteamSpy exposes aggregate, non-personal data: ownership estimates, playtime,
concurrent players, and crowd-sourced tags. We respect its published rate limit
(<= 1 request/second for the paged 'all' endpoint) and cache everything to disk.

Docs: https://steamspy.com/api.php

NOTE: This module makes real network calls and is meant to run on a machine with
open internet access. The course sandbox blocks steamspy.com, so for grading the
pipeline falls back to the bundled curated seed in data/sample/ (see load_sample).
"""
from __future__ import annotations

import time
from typing import Iterator

import requests

from ..config import REQUEST_TIMEOUT, STEAMSPY_DELAY_S, USER_AGENT

BASE = "https://steamspy.com/api.php"
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _get(params: dict, retries: int = 3, backoff: float = 2.0) -> dict:
    """GET with exponential backoff so a transient hiccup during a long (~90 min)
    collection doesn't abort the whole run. Raises after the final attempt."""
    last_exc = None
    for attempt in range(retries):
        try:
            resp = _session.get(BASE, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:                      # noqa: BLE001
            last_exc = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))   # 2s, 4s, 8s, ...
    raise last_exc


def parse_owners_lower(owners: str) -> int:
    """Lower bound of a SteamSpy owners range string -> int.

    SteamSpy returns ranges like '20,000 .. 50,000' or '1,000,000 .. 2,000,000'.
    The lower bound is enough to separate the indie long tail from blockbusters."""
    head = str(owners).split("..")[0].strip().replace(",", "").replace(" ", "")
    return int(head) if head.isdigit() else 0


def is_indie_candidate(record: dict, max_owners: int = 2_000_000,
                       max_reviews: int = 100_000) -> bool:
    """Cheap pre-enrichment filter to keep the indie wedge and drop AAA/mega-hits.

    Runs on the bulk 'all' records (which include owners + review counts but NOT
    tags), so we only pay the expensive per-app tag enrichment for games our
    customer actually competes with. See PLAN.md section 5.3."""
    owners_lo = parse_owners_lower(record.get("owners", ""))
    reviews = int(record.get("positive", 0) or 0) + int(record.get("negative", 0) or 0)
    return owners_lo < max_owners and reviews < max_reviews


def fetch_app(appid: int) -> dict:
    """Detailed record for one app: name, developer, tags{tag: votes}, owners, etc."""
    return _get({"request": "appdetails", "appid": appid})


def fetch_top_in_2weeks() -> dict:
    """The ~100 most-played games in the last two weeks (good demo seed).

    NOTE: like the 'all' endpoint, this does NOT include the 'tags' field — only
    appdetails does. Use it to get candidate appids, then enrich each via
    fetch_app() to obtain tags.
    """
    return _get({"request": "top100in2weeks"})


def list_appids(max_pages: int | None = 1, top2weeks: bool = False) -> list[int]:
    """Return candidate app ids (no tags yet) from the 'all' or top-2-weeks list."""
    if top2weeks:
        return [int(a) for a in fetch_top_in_2weeks().keys()]
    return [int(r.get("appid", 0)) for r in iter_all(max_pages=max_pages)
            if int(r.get("appid", 0)) > 0]


def iter_all(max_pages: int | None = None) -> Iterator[dict]:
    """Iterate every game SteamSpy knows, one page (~1000 games) at a time.

    The 'all' endpoint is paged and rate-limited to 1 request/second. Pass
    max_pages to cap collection for a proof-of-concept slice.
    """
    page = 0
    while True:
        if max_pages is not None and page >= max_pages:
            return
        data = _get({"request": "all", "page": page})
        if not data:
            return
        for appid, record in data.items():
            record.setdefault("appid", int(appid))
            yield record
        page += 1
        time.sleep(STEAMSPY_DELAY_S)


def normalize(record: dict) -> dict:
    """Map a raw SteamSpy record to our canonical schema (pipe-joined tags)."""
    tags = record.get("tags") or {}
    if isinstance(tags, dict):
        # keep tags ordered by vote count, strongest first
        tag_names = [t for t, _ in sorted(tags.items(), key=lambda kv: kv[1], reverse=True)]
    else:
        tag_names = list(tags)
    return {
        "appid": int(record.get("appid", 0)),
        "name": record.get("name", ""),
        "developer": record.get("developer", ""),
        "tags": "|".join(tag_names),
        "genres": (record.get("genre") or "").replace(", ", "|"),
        "owners": record.get("owners", ""),
        "price_usd": (int(record.get("price", 0) or 0) / 100.0),
        "positive": int(record.get("positive", 0) or 0),
        "negative": int(record.get("negative", 0) or 0),
        "release_year": "",
    }
