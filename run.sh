#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Meli — one-command local launcher (dev mode, no /opt install needed)
#
# What it does:
#   1. Creates ./.venv if missing, installs Python deps from pyproject.toml
#   2. Runs `npm install && npm run build` in webui/ if dist/ is missing
#   3. Launches `meli-web` — single uvicorn process serving:
#        • React UI at  http://127.0.0.1:17655/
#        • REST API at  http://127.0.0.1:17655/api/*
#
# Usage:
#   ./run.sh                # build (if needed) + run + open browser
#   ./run.sh --rebuild      # force a fresh webui rebuild
#   ./run.sh --no-open      # don't auto-launch the browser
#   ./run.sh --native       # open in borderless Electron window
#
# For full system install (systemd, desktop entry, /opt/meli, etc.),
# use ./install.sh instead.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV="$HERE/.venv"
WEBUI="$HERE/webui"
WEBUI_DIST="$WEBUI/dist"

REBUILD=false
PASSTHRU=()
for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=true ;;
        *) PASSTHRU+=("$arg") ;;
    esac
done

echo "[meli] checking Python venv..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip
echo "[meli] installing Python deps (editable)..."
python -m pip install --quiet -e .

echo "[meli] checking React webui build..."
if [ "$REBUILD" = true ] || [ ! -f "$WEBUI_DIST/index.html" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "[meli] error: 'npm' not found. Install Node.js >= 18 first." >&2
        echo "         (COSMIC / Pop!_OS: sudo apt install nodejs npm)" >&2
        exit 2
    fi
    pushd "$WEBUI" >/dev/null
    if [ ! -d node_modules ]; then
        echo "[meli] webui: npm install..."
        npm install --no-audit --no-fund --silent
    fi
    echo "[meli] webui: npm run build..."
    npm run build --silent
    popd >/dev/null
fi

# Point meli-web at the dev-tree dist (skip /opt lookup).
export MELI_WEBUI_DIST="$WEBUI_DIST"

echo "[meli] starting meli-web on http://127.0.0.1:17655/"
exec meli-web "${PASSTHRU[@]}"
