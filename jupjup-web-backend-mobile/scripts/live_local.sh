#!/bin/bash
# Reuse installed packages and verified caches. Never installs or downloads.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=/Users/minjun/orca/workspaces/dc2
export PYTHONPATH="$PWD/src:$BASE/PM/.venv/lib/python3.12/site-packages:$BASE/models/t25r-venv/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export JUPJUP_MODE=live JUPJUP_ANALYZER__ENGINE=local JUPJUP_ANALYZER__REQUIRED=true
export JUPJUP_ANALYZER__PROFILE="${JUPJUP_ANALYZER__PROFILE:-local-kanana-2b}"
export JUPJUP_ANALYZER_CACHE_DIR="$BASE/models"
export JUPJUP_BGE_CACHE_DIR="$BASE/models/bge-cache"
export JUPJUP_RECORDINGS_DIR="$PWD/var/live-recordings"
export JUPJUP_DB_PATH="${JUPJUP_DB_PATH:-$PWD/var/live-local.db}"
exec "$BASE/models/t25r-venv/bin/python" "$@"
