"""Live collector for Valve's official Steam Storefront & Web APIs.

Endpoints used (all public, free, governed by the Steam API Terms of Use):
  * appdetails:  https://store.steampowered.com/api/appdetails?appids=<id>
                 -> genres, description, price, release date, developer/publisher
  * appreviews:  https://store.steampowered.com/appreviews/<id>?json=1
                 -> public review summary (counts + score)

We throttle requests and cache, per Valve's guidance, and only ever read public
aggregate fields (no personal reviewer data).

NOTE: makes real network calls; the course sandbox blocks store.steampowered.com,
so the pipeline falls back to the bundled curated seed for grading.
"""
from __future__ import annotations

import time

import requests

from ..config import REQUEST_TIMEOUT, STEAM_STORE_DELAY_S, USER_AGENT

APPDETAILS = "https://store.steampowered.com/api/appdetails"
APPREVIEWS = "https://store.steampowered.com/appreviews/{appid}"
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def fetch_appdetails(appid: int, country: str = "us") -> dict | None:
    resp = _session.get(
        APPDETAILS,
        params={"appids": appid, "cc": country, "l": "english"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json().get(str(appid), {})
    if not payload.get("success"):
        return None
    time.sleep(STEAM_STORE_DELAY_S)
    return payload.get("data")


def fetch_review_summary(appid: int) -> dict:
    """Aggregate review counts/score only — no individual review bodies stored."""
    resp = _session.get(
        APPREVIEWS.format(appid=appid),
        params={"json": 1, "language": "all", "num_per_page": 0},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    summary = resp.json().get("query_summary", {})
    time.sleep(STEAM_STORE_DELAY_S)
    return summary


def normalize(appid: int, details: dict, review_summary: dict | None = None) -> dict:
    review_summary = review_summary or {}
    genres = "|".join(g["description"] for g in details.get("genres", []))
    devs = details.get("developers") or []
    year = ""
    rd = (details.get("release_date") or {}).get("date", "")
    for token in rd.replace(",", " ").split():
        if token.isdigit() and len(token) == 4:
            year = token
            break
    price = 0.0
    if details.get("is_free"):
        price = 0.0
    elif details.get("price_overview"):
        price = details["price_overview"].get("final", 0) / 100.0
    return {
        "appid": appid,
        "name": details.get("name", ""),
        "developer": devs[0] if devs else "",
        # storefront appdetails does NOT expose user tags; enrich via SteamSpy.
        "tags": genres,
        "genres": genres,
        "owners": "",
        "price_usd": price,
        "positive": int(review_summary.get("total_positive", 0)),
        "negative": int(review_summary.get("total_negative", 0)),
        "release_year": year,
    }
