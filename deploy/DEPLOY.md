# Deploying the demo on the CSIE workstation (ws1)

Constraints (from `ws1_usage.txt`): home dir `~/` must stay **under 800 MB**, so
the conda environment and all caches live in **`/tmp2/b12705015/`**. The repo code
itself is tiny (<1 MB) and lives in `~/BDA_Final`.

## Steps

```bash
# 0. (on your laptop) make sure the latest code is on GitHub
git add -A && git commit -m "Add deploy kit" && git push

# 1. SSH in
ssh ws1

# 2. Get the code (code in home is fine; it's tiny)
git clone https://github.com/NTUWhitefox/BDA_Final ~/BDA_Final
#   or, if already cloned:
cd ~/BDA_Final && git pull

# 3. One-time setup: conda env + deps + build, all caches in /tmp2
bash ~/BDA_Final/deploy/ws1_setup.sh

# 4. Run the server (foreground)
bash ~/BDA_Final/deploy/run.sh
```

The app now serves on `0.0.0.0:8731` on ws1. Endpoints: `/` (search),
`/graph` (relationship graph), `/api/*` (JSON).

## Accessing the demo

Pick whichever the campus network allows:

1. **SSH tunnel (always works, best for a grader on your laptop).**
   On your laptop, in a second terminal:
   ```bash
   ssh -L 8731:localhost:8731 ws1
   ```
   Then open http://localhost:8731/ locally.

2. **Direct hostname:port (if the workstation is reachable & the port is open).**
   Find the host: `hostname -f` on ws1 (e.g. `wsX.csie.ntu.edu.tw`), then visit
   `http://<that-host>:8731/`. May only work from inside the campus network /
   require a firewall exception.

3. **Public tunnel (for an off-campus URL on the PDF, optional bonus).**
   If outbound is allowed: `cloudflared tunnel --url http://localhost:8731`
   prints a temporary public `https://…trycloudflare.com` URL.

## Keep it running after you log out

```bash
tmux new -s bda          # start a tmux session
bash ~/BDA_Final/deploy/run.sh
#   detach: Ctrl-b then d   |   reattach later: tmux attach -t bda
# or:
nohup bash ~/BDA_Final/deploy/run.sh > ~/bda.log 2>&1 &
```

## Using live data (optional)

The build falls back to the bundled 42-game seed if no live data is present.
`ws1_setup.sh`/`run.sh` export `BDA_DATA_DIR=/tmp2/b12705015/data`, so all
collected data and built artifacts land in scratch (never the home quota).

**Indie-weighted bulk collection** (the realistic dataset — filters SteamSpy's
`all` list down to the indie wedge by owners/review thresholds *before* the
expensive per-app tag enrichment, so we don't waste requests on AAA hits):
```bash
ssh ws1
export BDA_DATA_DIR=/tmp2/b12705015/data
cd ~/BDA_Final && conda activate /tmp2/b12705015/bda_env
# runs at ~1 req/sec (SteamSpy rate limit); checkpoints every 50 games and
# RESUMES on re-run, so a dropped connection / wiped /tmp2 never restarts it.
python scripts/01_collect.py --source steamspy --indie --pages 25 --limit 3000
python scripts/02_build.py        # builds + pickles the engine in /tmp2/.../artifacts
```
Run the collection in `tmux` (it's long) — see "Keep it running" above. ~1,000
games enrich in ~25 min; the index then builds in <4 s.

Quick alternatives:
```bash
python scripts/01_collect.py --source steamspy --top2weeks   # ~100 most-played
python scripts/04_refresh.py --max-new 200                   # incremental new releases
```
Or `scp` a local `games_raw.csv` to `/tmp2/b12705015/data/raw/` before building.

## Troubleshooting

- **`/tmp2/b12705015` doesn't exist** → `mkdir -p /tmp2/b12705015` first.
- **Port already in use** (shared machine) → pick another: `PORT=8742 bash deploy/run.sh`.
- **conda command not found inside script** → the script bootstraps miniconda into
  `/tmp2` automatically; just re-run `ws1_setup.sh`.
- **pip can't reach PyPI** → the campus may block outbound; tell me and we'll switch
  to copying pre-downloaded wheels.
- **home quota exceeded** → check `du -sh ~/.conda ~/.cache`; those should be empty
  because the script redirects them to /tmp2. If not, `rm -rf ~/.cache/pip`.
- **`/tmp2` got cleared** (scratch is periodically wiped) → just re-run `ws1_setup.sh`.
