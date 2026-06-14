#!/usr/bin/env bash
# Start the FastAPI demo on ws1. Run after ws1_setup.sh.
#   bash ~/BDA_Final/deploy/run.sh            # foreground
#   PORT=8731 bash ~/BDA_Final/deploy/run.sh  # custom port
# To keep it alive after logout, run inside tmux/screen or with nohup (see DEPLOY.md).
set -euo pipefail

USER_ID="${USER_ID:-b12705015}"
SCRATCH="/tmp2/${USER_ID}"
ENV_PREFIX="${SCRATCH}/bda_env"
REPO_DIR="${REPO_DIR:-$HOME/BDA_Final}"
PORT="${PORT:-8731}"
# Must match ws1_setup.sh so the server reads the index built into /tmp2.
export BDA_DATA_DIR="${BDA_DATA_DIR:-$SCRATCH/data}"

if command -v conda >/dev/null 2>&1; then
  CONDA_BASE="$(conda info --base)"
else
  CONDA_BASE="$SCRATCH/miniconda"
fi
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_PREFIX"

cd "$REPO_DIR"
echo ">> serving on 0.0.0.0:$PORT  (Ctrl-C to stop)"
echo ">> from your laptop:  ssh -L $PORT:localhost:$PORT ws1   then open http://localhost:$PORT/"
exec python -m uvicorn bda.api.app:app --app-dir src --host 0.0.0.0 --port "$PORT"
