#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$REPO_ROOT/custom_components"
DST_DIR="$SCRIPT_DIR/config/custom_components"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: Source folder not found: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "$DST_DIR"

echo "Syncing custom_components -> dev-instance/config/custom_components" 
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "$SRC_DIR/" "$DST_DIR/"
else
  rm -rf "$DST_DIR"/*
  cp -R "$SRC_DIR/"* "$DST_DIR/"
fi

echo "Starting Home Assistant (docker compose)" 
if docker compose version >/dev/null 2>&1; then
  docker compose -f "$SCRIPT_DIR/docker-compose.yaml" up -d
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "$SCRIPT_DIR/docker-compose.yaml" up -d
else
  echo "ERROR: docker compose not found (need 'docker compose' or 'docker-compose')." >&2
  exit 1
fi

echo "Home Assistant should be available at http://localhost:8123" 
