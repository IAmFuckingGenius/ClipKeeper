#!/usr/bin/env bash
# ClipKeeper — Launch Script
# Usage:
#   bash run.sh           — Start/toggle ClipKeeper
#   bash run.sh --daemon  — Start in background (no window)
#   bash run.sh --quit    — Stop the daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 src/main.py "$@"
