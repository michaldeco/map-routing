#!/usr/bin/env bash
# Development: the API (restarts on Python changes) and Vite's dev server (updates the
# browser on frontend changes). Open http://127.0.0.1:5173; Vite forwards /api to the API.
# Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run map-routing api --reload &
api=$!
trap 'kill "$api" 2> /dev/null || true' EXIT

cd web && pnpm run dev
