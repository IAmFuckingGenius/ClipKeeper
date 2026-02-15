#!/usr/bin/env bash
# ClipKeeper bootstrap installer (no git clone required).
# Designed for usage via curl:
#   curl -fsSL <raw-url>/bootstrap-install.sh | bash -s -- --repo owner/repo --ref main

set -euo pipefail

REPO="${CLIPKEEPER_REPO:-}"
REF="${CLIPKEEPER_REF:-main}"
SKIP_DEPS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="$2"
      shift 2
      ;;
    --ref)
      REF="$2"
      shift 2
      ;;
    --skip-deps)
      SKIP_DEPS=true
      shift
      ;;
    *)
      echo "[ClipKeeper] Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$REPO" ]]; then
  echo "[ClipKeeper] Missing --repo owner/repo" >&2
  echo "Example: --repo yourname/clipkeeper --ref main" >&2
  exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[ClipKeeper] curl is required" >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo "[ClipKeeper] tar is required" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ARCHIVE_PATH="$TMP_DIR/clipkeeper.tar.gz"
EXTRACT_DIR="$TMP_DIR/extract"
mkdir -p "$EXTRACT_DIR"

URLS=(
  "https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"
  "https://github.com/${REPO}/archive/refs/tags/${REF}.tar.gz"
  "https://github.com/${REPO}/archive/${REF}.tar.gz"
)

DOWNLOADED=""
for url in "${URLS[@]}"; do
  if curl -fsSL "$url" -o "$ARCHIVE_PATH"; then
    DOWNLOADED="$url"
    break
  fi
done

if [[ -z "$DOWNLOADED" ]]; then
  echo "[ClipKeeper] Failed to download repository archive for ${REPO}@${REF}" >&2
  exit 1
fi

tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"
SRC_DIR="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

if [[ -z "$SRC_DIR" ]] || [[ ! -f "$SRC_DIR/install.sh" ]]; then
  echo "[ClipKeeper] install.sh not found in downloaded archive" >&2
  exit 1
fi

INSTALL_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/clipkeeper"
INSTALL_SRC_DIR="$INSTALL_BASE/source"
mkdir -p "$INSTALL_BASE"
rm -rf "$INSTALL_SRC_DIR"
mv "$SRC_DIR" "$INSTALL_SRC_DIR"

chmod +x "$INSTALL_SRC_DIR/install.sh"

echo "[ClipKeeper] Downloaded from: $DOWNLOADED"
echo "[ClipKeeper] Source installed to: $INSTALL_SRC_DIR"

if [[ "$SKIP_DEPS" == true ]]; then
  bash "$INSTALL_SRC_DIR/install.sh" --skip-deps
else
  bash "$INSTALL_SRC_DIR/install.sh"
fi

echo "[ClipKeeper] Bootstrap install completed"
