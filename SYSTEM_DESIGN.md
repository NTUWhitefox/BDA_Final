# Indie Game Discovery Engine — System Design

*This document covers the technical system design per SPEC.md §4. Use it as the "System Design" section of the final PDF report.*

---

## 4.1  Data Sources

All data collected is **public and aggregate — no personal data, no scraping of private content**.

| Source | What we collect | How | Legal basis |
|---|---|---|---|
| **SteamSpy API** (primary) | Ownership estimates, playtime stats, crowd-sourced player tags, review counts | REST `appdetails` + paged `all` endpoint; rate-limited to ≤ 1 req/s as requested | Public, unofficial, no key required; we respect the stated rate limit and cache to disk |
| **Steam Web API / Storefront API** | Genres, release date, price, description, developer/publisher, review score | `appdetails` + `appreviews` endpoints | Official, free; governed by the Steam API Terms of Use |
| **IGDB API** (Twitch/Amazon) | Normalised genres, themes, keywords, franchises, aggregated ratings | Twitch OAuth + REST API | Free for non-commercial use under the Twitch Developer Service Agreement |
| **Bundled curated seed** (`data/sample/games_sample.csv`) | 42 hand-selected indie games with manually verified tags | Committed to repo — no network call needed | Our own curation; used as the cold-start fallback |

### Indie-wedge filtering (pre-enrichment)

SteamSpy's `all` endpoint returns ~1,000 records per page at minimal cost (no tag data). We apply a **cheap pre-enrichment filter** on these bulk records — dropping games whose estimated owner lower-bound ≥ 2,000,000 or whose total review count ≥ 100,000 — before issuing the expensive per-app `appdetails` call. On a 25-page crawl this kept ~33% of candidates (indie long tail) and avoided spending API quota on AAA/mega-hits our customers don't compete with.

### Robustness

- **Checkpoint / resume**: the collector flushes collected rows to CSV every 50 games and, on rerun, reads the existing CSV to skip already-collected appids. A 90-minute collection survives a dropped SSH connection or a periodic `/tmp2` wipe without restarting.
- **Exponential-backoff retry**: 3 attempts with 2 s / 4 s / 8 s delays on transient HTTP errors.
- **Rate compliance**: `STEAMSPY_DELAY_S = 1.1 s` between requests; `STEAM_STORE_DELAY_S = 1.5 s`.

---

## 4.2  Storage and Processing

### Storage layout

```
/tmp2/b12705015/data/        (scratch — large, regenerable; not in home quota)
    raw/
        games_raw.csv        <- raw collector output; append-only during collection
    artifacts/
        games.csv            <- cleaned, merged, validated
        engine.pkl           <- serialised fitted engine (loads in < 1 s on restart)
        index_meta.json      <- build metadata (game count, tag count, build time)

~/BDA_Final/                 (home — code only; < 1 MB)
    data/sample/
        games_sample.csv     <- 42-game curated seed (committed to repo)
```

The `BDA_DATA_DIR` environment variable redirects the large paths to scratch space (`/tmp2`) without touching the home directory quota (800 MB on the school workstation).

### Processing pipeline

```
Raw CSV  ->  load_games()  ->  RecommenderEngine.__init__()
                                    |
                         +----------+------------------+
                    (1) TF-IDF           (2) kNN index
                    tag weighting        (sparse top-K)
                         |                     |
                    (3) Tag co-occurrence graph |
                        (Louvain communities)   |
                         |                     |
                    (4) Game similarity graph   |
                        (PageRank hub scores)   |
                         +----------+----------+
                              engine.pkl  <- pickle serialised
```

**Step 1 — Tag-rarity weighting (TF-IDF).**
Each game's tag list is binarised (`sklearn.preprocessing.MultiLabelBinarizer`) into a games × tags count matrix, then reweighted with `sklearn.feature_extraction.text.TfidfTransformer`. Rare tags (e.g. "Hex Grid") receive higher weight than ubiquitous ones ("Indie", "Singleplayer"), so similarity is driven by specific niche signals rather than genre boilerplate.

**Step 2 — Sparse top-K nearest neighbours.**
Instead of materialising the full n × n cosine-similarity matrix (O(n²) memory — ~10 GB at 50k games), we use `sklearn.neighbors.NearestNeighbors(n_neighbors=50, metric='cosine', algorithm='brute')`. Only each game's 50 closest neighbours are retained, reducing memory to O(n·K) (a few MB at 50k games). Query results are identical to the full-matrix approach for any top-k ≤ 50. This is the key scalability fix: 1,015-game build completes in **3.74 s, 199 MB peak RAM**.

**Step 3 — Tag co-occurrence graph and Louvain community detection.**
A tag × tag co-occurrence matrix is computed (`counts.T @ counts`) and loaded into a `networkx.Graph`. `nx.community.louvain_communities()` with weighted edges discovers **micro-niches** (e.g. "precision-platformer", "city-builder", "cozy-farming") without requiring a pre-specified cluster count. Each game is assigned to the niche whose defining tags dominate its tag list.

**Step 4 — PageRank on the game-similarity graph.**
A game-similarity graph (edges = kNN pairs above a 0.15 similarity threshold) is built and `nx.pagerank()` is run on it. High-PageRank games are **audience hubs** — games where an audience concentrates and cross-play is highest. These are surfaced to developers as the concrete competitor targets to study and streamers to approach.

**Reference to course tools:**

| Concern | POC (this implementation) | Production (10x / 100x scale) |
|---|---|---|
| Ingestion decoupling | Direct API calls, sequential | **Kafka** topic of new-release / review events |
| Raw storage | Local CSV / Parquet | **HDFS / S3 object storage** (immutable raw layer) |
| Batch processing | pandas + sklearn | **Apache Spark** (MLlib TF-IDF, GraphFrames PageRank / Louvain) |
| Vector search | sklearn NearestNeighbors (brute) | **FAISS** (approximate kNN, incremental upserts) |
| Graph store | NetworkX in-memory | **Neo4j** (game-tag-developer relationships) |
| Metadata store | CSV | **MongoDB** or **DuckDB** (analytics queries) |
| Serving | FastAPI + pickle | Same FastAPI layer, backed by the stores above |

---

## 4.3  Delivery

The system is delivered as a **FastAPI web application** served by **uvicorn** on port 8731.

### Pages

| URL | Description |
|---|---|
| `GET /` | Search + discovery report page: search by name, get niche profile, similar games, competitors, and positioning gaps |
| `GET /graph` | Interactive force-directed game-relationship graph (vis-network.js, coloured by niche, sized by PageRank) |

### JSON API

| Endpoint | Description |
|---|---|
| `GET /api/health` | Returns `{status, games, niches}` — used for monitoring |
| `GET /api/search?q=<name>` | Name substring search across the catalogue |
| `GET /api/similar/{appid}` | Top-k tag-vector-cosine nearest neighbours |
| `GET /api/competitors/{appid}` | Nearest neighbours within the same Louvain niche |
| `GET /api/niche/{appid}` | Niche profile: defining tags, audience hubs, sibling games, positioning gaps |
| `GET /api/graph?threshold=0.2` | Full graph payload for the relationship visualisation |

### Cold-start fast loading

On the first request after a server restart, `get_engine()` checks whether a serialised engine pickle exists and is newer than the source CSV. If so, it loads from the pickle (< 1 s). Otherwise it rebuilds the engine (~4 s for 1,015 games) and writes a fresh pickle. An `lru_cache(maxsize=1)` then serves all subsequent requests from the in-memory engine with zero rebuild cost.

### Public access

The demo is deployed on the CSIE workstation **ws1.csie.ntu.edu.tw**:
- **Live demo**: `http://ws1.csie.ntu.edu.tw:8731/`
- **Landing page**: `https://www.csie.ntu.edu.tw/~b12705015/` (static homepage via CSIE's `~/htdocs/` service)
- SSH tunnel for off-campus: `ssh -L 8731:localhost:8731 ws1` -> `http://localhost:8731/`

---

## 4.4  Architecture Diagram

```
+--------------------------------- Data Collection ----------------------------------+
|                                                                                    |
|  SteamSpy API          Steam Store API          IGDB API                          |
|  (ownership, tags)     (genres, price)          (themes, keywords)                |
|       |                       |                       |                           |
|       +---------------+-------+                       |                           |
|                       v                               |                           |
|             01_collect.py                             |                           |
|             (indie filter -> tag enrichment           |                           |
|              -> checkpoint every 50 rows)             |                           |
|                       |                  merge.py <---+                           |
|                       |                  (dedup by appid,                         |
|                       v                   richest tags win)                       |
|               games_raw.csv                                                       |
+------------------------+-----------------------------------------------------------+
                         |
+------------------------v-------------- Build Pipeline ----------------------------+
|                                                                                    |
|  02_build.py  ->  load_games()  ->  RecommenderEngine(games)                      |
|                                           |                                       |
|                           +---------------+------------------+                    |
|                      TF-IDF        Sparse kNN           Louvain                   |
|                      weighting     (top-50, cosine)     niche communities         |
|                           |               |                  |                    |
|                           +---------------+------------------+                    |
|                                           |                                       |
|                                    PageRank (hub scores)                          |
|                                           |                                       |
|                                    engine.pkl  (serialised to disk)               |
+------------------------------------------------------------------------------------+
                         |
+------------------------v-------------- Serving ------------------------------------+
|                                                                                    |
|  app.py  (FastAPI + uvicorn, port 8731)                                            |
|       |                                                                            |
|       +-- GET /                -> index.html (search + report)                   |
|       +-- GET /graph           -> graph.html (vis-network force-directed)         |
|       +-- GET /api/*           -> JSON (similar, competitors, niche, graph)       |
|                                                                                    |
|  Consumers:                                                                        |
|       Indie developer  ->  enters Steam appid  ->  gets niche / competitors /     |
|                            positioning gaps / audience hubs                        |
|       Player           ->  searches game name  ->  "games like X"                 |
+------------------------------------------------------------------------------------+
```

---

## 4.5  Scalability and Cost Sketch

### Current proof-of-concept

| Metric | Value |
|---|---|
| Games in index | 1,015 (indie-filtered from SteamSpy) |
| Build time | 3.74 s wall clock |
| Peak RAM during build | 199 MB |
| Engine pickle size | 2.4 MB |
| Tags discovered | 418 unique |
| Niches (Louvain communities) | 5 |
| Enrichment rate | ~1 game/s (SteamSpy rate limit) |
| Data in /tmp2 scratch | ~3 MB total |
| Home directory usage | 381 MB (under 800 MB quota) |

### At 10x (10,000 games)

The kNN approach scales linearly: O(n·K) memory, so 10k games at K=50 uses roughly 2–3 MB for the index arrays. Build time stays under a minute on a single machine. No architecture changes required.

Enrichment time: ~3 hours at 1 game/s (SteamSpy rate). Mitigated by the checkpoint/resume system.

### At 100x (100,000 games)

- The `NearestNeighbors(algorithm='brute')` kNN becomes slow (O(n²) compute). Replace with **FAISS IVF index** for approximate search — 100k-game queries in milliseconds.
- NetworkX Louvain on 100k nodes × 5M edges may become slow. Migrate to **Apache Spark GraphFrames** (distributed PageRank + Louvain at scale).
- Batch enrichment from a single machine at 1 req/s takes ~27 hours. Mitigate with multiple collection workers behind different IPs, or switch to bulk datasets (Kaggle snapshots + incremental diffs).
- Cost estimate (single small VM, ~$30/month): feasible for a scrappy product. The index is compute-once, serve-many — marginal cost per query is negligible. Incremental refresh via `04_refresh.py` avoids full rebuilds.

---

## 4.6  Future Work

### Higher-priority improvements

**1. Smarter indie game identification**
The current filter (`owners_lower < 2,000,000 AND reviews < 100,000`) is crude. Several problems:
- SteamSpy ownership numbers are modelled estimates with wide confidence intervals, not ground-truth.
- Owner count conflates "small game" with "indie": a small AAA spin-off or a free-to-play Valve game might have few owners but is not an indie game.
- The threshold is hard-coded and not calibrated on labeled data.

Better approaches (in order of implementation effort):
- **Publisher/developer signals**: games self-published by a solo developer or micro-studio (developer name = publisher name, no known large publisher in a blocklist) are likely indie regardless of owner count.
- **Price range**: indie games cluster at $5–$20; free-to-play or $60+ titles are much more likely to be AAA. Adding a price band filter improves precision.
- **Store tag "Indie" + developer history**: SteamSpy's per-app genre field often includes "Indie"; cross-referencing the developer's entire catalogue size (total owned games by the same developer) identifies micro-studios directly.
- **Trained classifier**: with a modest labeled dataset (~500 indie / ~500 non-indie games), a logistic regression over (owner count, review count, price, genre flags, developer portfolio size) would give calibrated indie probability scores rather than a hard threshold.

**2. Collaborative filtering (behavioral signal)**
The current engine is purely content-based (tags -> TF-IDF cosine similarity). Two games with different genres but overlapping fanbases (e.g. Hades and Celeste) are only similar if they share tags. A collaborative signal — built from Steam review co-occurrence or SteamSpy owner estimates — would capture taste-based similarity that tags miss, improving recommendations for games that already have reviews.

**3. Streamer and community targeting output**
The `niche_profile` endpoint identifies audience-hub games (high PageRank) but stops short of naming the actual streamers, subreddits, or Discord communities that cover them. Adding Twitch category data, YouTube search signals, or Reddit API data would turn the abstract "hub game" into a concrete, actionable marketing list — the highest-value output for an indie developer planning outreach.

**4. Cross-platform coverage (itch.io, GOG)**
The current pipeline covers Steam only. Many indie games launch on itch.io first or exclusively. Adding itch.io public listings (no auth needed for browse pages) would extend coverage of the micro-indie long tail that is exactly the wedge segment.

**5. Freshness and streaming updates**
A game that released last week is invisible to the current batch-built index until the next manual rebuild. A daily `04_refresh.py` cron job (incremental: only new appids) keeps the catalogue fresh without full rebuilds. At scale, a Kafka-based streaming pipeline (new-release events -> enrichment workers -> incremental FAISS upserts) would reduce latency to minutes.

**6. Evaluation / quality metrics**
There is currently no offline evaluation of recommendation quality. Adding a holdout evaluation (e.g., for games with known "similar games" lists from Steam's own "More Like This" section, measure precision@k and recall@k against the engine's output) would give an objective quality signal and guide hyperparameter choices (K in kNN, TF-IDF smoothing, Louvain resolution).

### Lower-priority / longer-term

- **Personalisation**: once a developer profile exists (games they've worked on, target audience), recommendations could be filtered to games in directly adjacent niches rather than global similarity.
- **UMAP niche map**: a 2D projection of the TF-IDF game vectors (UMAP/t-SNE) would produce a visually compelling "niche landscape" — useful as a product demo and for explaining positioning to non-technical users.
- **A/B testing infrastructure**: once the product has paying users, A/B testing whether collaborative vs. content-based recommendations lead to better marketing ROI is the core feedback loop for improving the model.
