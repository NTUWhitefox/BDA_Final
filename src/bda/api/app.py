"""FastAPI delivery layer for the discovery engine.

Run:
    uvicorn bda.api.app:app --reload --app-dir src
then open:
    http://127.0.0.1:8000/        search + discovery report
    http://127.0.0.1:8000/graph   interactive game relationship graph
JSON API:
    GET /api/search?q=hades
    GET /api/similar/{appid}
    GET /api/competitors/{appid}
    GET /api/niche/{appid}
    GET /api/graph
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ..collect.load_sample import load_games
from ..config import ENGINE_PKL, RAW_CSV, SAMPLE_CSV
from ..process.engine import RecommenderEngine

app = FastAPI(title="Indie Game Discovery POC", version="0.2.0")
STATIC = Path(__file__).parent / "static"


def _pickle_is_fresh() -> bool:
    """True if a saved engine exists and is newer than its source data, so we can
    load it instead of rebuilding the index cold on the first request."""
    if not ENGINE_PKL.exists():
        return False
    built = ENGINE_PKL.stat().st_mtime
    for src in (RAW_CSV, SAMPLE_CSV):
        if src.exists() and src.stat().st_mtime > built:
            return False  # data changed since the engine was built -> rebuild
    return True


@lru_cache(maxsize=1)
def get_engine() -> RecommenderEngine:
    if _pickle_is_fresh():
        try:
            return RecommenderEngine.load(ENGINE_PKL)
        except Exception:
            pass  # corrupt/incompatible pickle -> fall back to a fresh build
    games, _ = load_games()
    engine = RecommenderEngine(games)
    try:
        engine.save(ENGINE_PKL)  # cache for the next restart
    except Exception:
        pass
    return engine


@app.get("/api/health")
def health() -> dict:
    eng = get_engine()
    return {"status": "ok", "games": int(len(eng.games)), "niches": eng.n_niches}


@app.get("/api/search")
def search(q: str) -> list:
    return [h.__dict__ for h in get_engine().search(q)]


@app.get("/api/similar/{appid}")
def similar(appid: int, k: int = 5) -> list:
    hits = get_engine().similar(appid, k=k)
    if not hits:
        raise HTTPException(404, f"appid {appid} not found")
    return [h.__dict__ for h in hits]


@app.get("/api/competitors/{appid}")
def competitors(appid: int, k: int = 5) -> list:
    return [h.__dict__ for h in get_engine().competitors(appid, k=k)]


@app.get("/api/niche/{appid}")
def niche(appid: int) -> dict:
    eng = get_engine()
    prof = eng.niche_profile(appid)
    if not prof:
        raise HTTPException(404, f"appid {appid} not found")
    prof["positioning_gaps"] = eng.niche_gaps(appid)
    return prof


@app.get("/api/graph")
def graph(threshold: float = 0.2) -> dict:
    return get_engine().graph_data(threshold=threshold)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/graph", response_class=HTMLResponse)
def graph_page() -> str:
    return (STATIC / "graph.html").read_text(encoding="utf-8")
