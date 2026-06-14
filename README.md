# BDA Final — Indie Game Discovery Engine (Proof of Concept)

A data product that monetizes public game metadata to solve the **indie game
discovery bottleneck**. It is double-sided:

- **Players** get *"games like X"* recommendations and a niche map to explore.
- **Indie developers** (the paying customer) get their **direct competitors**,
  the **micro-niche** their game sits in, the **audience hubs** where that
  audience concentrates (for targeted marketing), and **positioning gaps** to
  differentiate.

See `../PLAN.md` (sections 2–4) for the business case, evidence of demand /
willingness to pay, and the full system design.

## How it works

```
 Data sources                Ingestion          Processing (Spark-mappable)        Serving
 ─────────────               ─────────          ───────────────────────────        ───────
 Steam Web/Store API ─┐                       ┌─ TF-IDF tag-rarity weighting ─┐
 SteamSpy API ────────┼─ collectors ─► raw ──►├─ game→game cosine similarity  ├─► FastAPI + web UI
 Kaggle/seed CSV ─────┘     (cached)   CSV     ├─ tag co-occurrence + Louvain  │   (JSON API)
                                               └─ PageRank (audience hubs) ────┘
```

The modelling is the hybrid from PLAN.md §4.3:

1. **Tag-rarity weighting** — a games × tags matrix passed through TF-IDF so
   generic tags (`Indie`, `Singleplayer`) don't dominate over defining ones.
2. **Game→game similarity** — cosine similarity over those vectors → *"games like X"*.
3. **Tag co-occurrence graph + Louvain communities** — discovers micro-niches
   (the multi-level *tag→tag→game* relation).
4. **PageRank** on the game-similarity graph — finds hub games where an audience
   concentrates (competitor/streamer targeting).

At 10×/100× scale the identical steps map onto **Spark** (matrix/TF-IDF), **GraphFrames**
(communities/PageRank), a **vector index (FAISS)** for nearest neighbours, **Kafka**
for streaming review/release updates, and **Neo4j/MongoDB** as serving stores.

## Data sources (all public & legal)

| Source | What | Access | Notes |
|---|---|---|---|
| Steam Web/Storefront API | genres, price, release, dev, public review counts | free, official, ToS-bound | rate-limited; we throttle + cache |
| SteamSpy API | aggregate ownership, playtime, crowd tags | free, no key | <=1 req/s; no PII |
| Kaggle open Steam datasets | pre-collected snapshots | open license | bootstraps cold-start |

We only collect **public, aggregate, non-personal** data (GDPR/PDPA-safe) and do
**not** scrape SteamDB (prohibited by their FAQ) — SteamSpy/official API give the
same signals. IGDB can be added for richer metadata (free for non-commercial use).

## Setup

```bash
cd BDA_Final
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
```

## Run

The pipeline runs **offline** on the bundled curated seed
(`data/sample/games_sample.csv`, 42 real games across roguelike, sim/builder,
metroidvania/narrative and co-op niches). No network or API key required.

```bash
# 1. Build the index (reads live data if present, else the bundled seed)
python scripts/02_build.py

# 2. Command-line discovery report
python scripts/03_query.py --appid 1145360     # Hades
python scripts/03_query.py --name "Stardew"

# 3. Web app + JSON API  ->  http://127.0.0.1:8000/   (search + discovery report)
#                          http://127.0.0.1:8000/graph (game relationship graph)
uvicorn bda.api.app:app --reload --app-dir src
```

### (Optional) collect live data

Run on a machine with open internet (the course sandbox blocks Steam/SteamSpy):

```bash
python scripts/01_collect.py --source steamspy --pages 5        # ~5k games
python scripts/01_collect.py --source steamspy --top2weeks      # top-100 seed
python scripts/01_collect.py --source steam --appids 1145360 646570 367520
```

This writes `data/raw/games_raw.csv`, which `02_build.py` automatically prefers
over the bundled seed.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/health` | dataset size + niche count |
| `GET /api/search?q=hades` | matching games |
| `GET /api/similar/{appid}` | players: games like this |
| `GET /api/competitors/{appid}` | developers: direct rivals in the niche |
| `GET /api/niche/{appid}` | niche tags, audience hubs, positioning gaps |
| `GET /api/graph` | nodes + edges for the relationship graph |

## Layout

```
BDA_Final/
├── data/sample/games_sample.csv   curated real-game seed (committed)
├── src/bda/
│   ├── collect/    steamspy.py, steam_store.py, igdb.py (live), load_sample.py,
│   │                merge.py (multi-source), newreleases.py (freshness)
│   ├── process/    engine.py  (TF-IDF + graph + PageRank recommender)
│   └── api/        app.py + static/index.html (FastAPI + dashboard)
├── scripts/        01_collect.py · 02_build.py · 03_query.py · 04_refresh.py
└── requirements.txt
```

## Keeping data fresh & adding sources

`scripts/04_refresh.py` (using `collect/newreleases.py`) diffs the live Steam app
list against games already collected and enriches only the new titles, so the
index keeps up with new releases (run it on a schedule). `collect/merge.py`
combines multiple sources (SteamSpy + Storefront + IGDB) into the canonical
schema, keeping the richest tags and back-filling gaps. See PLAN.md §5.

## Reproducing the demand evidence

The data-collection methods used to establish demand (Steam/SteamSpy scraping of
release counts, review distributions, tag landscapes) reuse the same collectors
in `src/bda/collect/`. See `../PLAN.md` §3 for the full evidence and sources.
