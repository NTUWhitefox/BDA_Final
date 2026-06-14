#!/usr/bin/env bash
# One-time setup on the CSIE workstation (ws1).
# Keeps the home dir well under the 800MB quota by putting the conda env,
# all package caches, and tmp files under /tmp2 (scratch space).
#
#   ssh ws1
#   git clone https://github.com/NTUWhitefox/BDA_Final ~/BDA_Final   # if not cloned
#   bash ~/BDA_Final/deploy/ws1_setup.sh
set -euo pipefail

USER_ID="${USER_ID:-b12705015}"
SCRATCH="/tmp2/${USER_ID}"
ENV_PREFIX="${SCRATCH}/bda_env"
REPO_DIR="${REPO_DIR:-$HOME/BDA_Final}"

echo ">> scratch dir: $SCRATCH"
mkdir -p "$SCRATCH"/{conda_pkgs,pip_cache,tmp,miniconda,.cache,data}

# Redirect every cache that would otherwise fill the home quota.
export CONDA_PKGS_DIRS="$SCRATCH/conda_pkgs"
export PIP_CACHE_DIR="$SCRATCH/pip_cache"
export TMPDIR="$SCRATCH/tmp"
# Disable the Anaconda TOS interactive plugin — it crashes in non-interactive SSH sessions.
export CONDA_NO_PLUGINS=true
# Keep large collected data + built artifacts OUT of the home quota (in /tmp2).
export BDA_DATA_DIR="${BDA_DATA_DIR:-$SCRATCH/data}"

# 1. Ensure conda is available; if not, bootstrap miniconda INTO /tmp2 (never home).
if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
  echo ">> using existing conda at $CONDA_BASE"
else
  echo ">> conda not found - installing miniconda into $SCRATCH/miniconda ..."
  INSTALLER="$SCRATCH/tmp/miniconda.sh"
  curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o "$INSTALLER"
  bash "$INSTALLER" -b -u -p "$SCRATCH/miniconda"
  CONDA_BASE="$SCRATCH/miniconda"
fi
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

# 2. Create the environment in /tmp2 (prefix install, not name-based in home).
if [ ! -d "$ENV_PREFIX" ]; then
  echo ">> creating env at $ENV_PREFIX"
  conda create -y --solver=classic -p "$ENV_PREFIX" python=3.10
fi
conda activate "$ENV_PREFIX"

# 3. Install Python deps (wheels cached in /tmp2).
echo ">> installing requirements"
pip install --no-input -r "$REPO_DIR/requirements.txt"

# 4. Build the recommendation index.
#    Uses data/raw/games_raw.csv if you copied it over, else the bundled 42-game seed.
echo ">> building index"
cd "$REPO_DIR"
python scripts/02_build.py

echo
echo ">> home dir usage:"; du -sh "$HOME" 2>/dev/null || true
echo ">> DONE. Env: $ENV_PREFIX"
echo ">> Start the server with:  bash $REPO_DIR/deploy/run.sh"
