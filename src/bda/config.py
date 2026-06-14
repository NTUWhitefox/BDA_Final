"""Central paths and constants for the pipeline."""
from pathlib import Path

# Repo root = three levels up from this file (src/bda/config.py -> repo/)
ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
RAW_DIR = DATA_DIR / "raw"
ARTIFACTS_DIR = ROOT / "artifacts"

SAMPLE_CSV = SAMPLE_DIR / "games_sample.csv"
# Where collectors write freshly fetched data, and where the builder reads from
# (falls back to the bundled sample when no raw collection exists).
RAW_CSV = RAW_DIR / "games_raw.csv"

# Built index artifacts
GAMES_PARQUET = ARTIFACTS_DIR / "games.parquet"
GAMES_CSV = ARTIFACTS_DIR / "games.csv"
META_JSON = ARTIFACTS_DIR / "index_meta.json"

# Polite networking defaults for live collectors (Steam/SteamSpy ToS friendly)
REQUEST_TIMEOUT = 20
STEAMSPY_DELAY_S = 1.1        # SteamSpy asks for <= 1 req/sec for 'all'
STEAM_STORE_DELAY_S = 1.5     # storefront API is unofficially rate-limited
USER_AGENT = "BDA-Final-Research/0.1 (academic project; contact via repo)"

for _d in (RAW_DIR, ARTIFACTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
