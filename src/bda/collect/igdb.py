"""IGDB collector (Twitch/Amazon) - richer normalised metadata.

IGDB is free for non-commercial use under the Twitch Developer Service Agreement.
Auth = Twitch OAuth client-credentials flow. Set env vars:
    IGDB_CLIENT_ID, IGDB_CLIENT_SECRET

Provides genres, themes, keywords, franchises and aggregated ratings - useful for
enriching games that have sparse Steam tags, and for cross-store coverage. This is
real, runnable code but needs credentials + open network, so it is documented as a
secondary source rather than exercised in the offline POC (see PLAN.md section 5).
"""
from __future__ import annotations

import os

import requests

from ..config import REQUEST_TIMEOUT, USER_AGENT

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GAMES_URL = "https://api.igdb.com/v4/games"


def get_token() -> str:
    cid, secret = os.environ.get("IGDB_CLIENT_ID"), os.environ.get("IGDB_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("Set IGDB_CLIENT_ID and IGDB_CLIENT_SECRET to use IGDB.")
    r = requests.post(TOKEN_URL, params={
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials"}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_games(limit: int = 100, offset: int = 0) -> list:
    """Pull a page of games with themes/keywords/genres via the IGDB query DSL."""
    token = get_token()
    headers = {
        "Client-ID": os.environ["IGDB_CLIENT_ID"],
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    body = (
        "fields name, genres.name, themes.name, keywords.name, "
        "total_rating, total_rating_count, involved_companies.company.name; "
        f"where total_rating_count > 5; limit {limit}; offset {offset};"
    )
    r = requests.post(GAMES_URL, headers=headers, data=body, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def normalize(rec: dict) -> dict:
    names = lambda key: "|".join(x["name"] for x in rec.get(key, []) if "name" in x)
    tags = "|".join(t for t in [names("genres"), names("themes"), names("keywords")] if t)
    return {
        "appid": int(rec.get("id", 0)),          # IGDB id (namespace differs from Steam)
        "name": rec.get("name", ""),
        "developer": "",
        "tags": tags,
        "genres": names("genres"),
        "owners": "",
        "price_usd": 0.0,
        "positive": int(rec.get("total_rating_count", 0) or 0),
        "negative": 0,
        "release_year": "",
    }
