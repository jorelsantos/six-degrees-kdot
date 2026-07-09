#!/usr/bin/env bash
#
# One-command local demo (plan 2026-07-09-002, U2).
#
# Resets the local Cloudflare D1 database, reseeds it from the exported
# serving SQL, then starts the Worker (:8787) and the Next.js frontend (:3000)
# together. Ctrl-C stops both.
#
# The reset is load-bearing: the exporter emits `INSERT OR IGNORE`, so seeding
# on top of an existing local D1 would silently skip every artist already
# present and keep showing stale (pre-bake) data. Wiping the local D1 dir first
# guarantees a fresh seed reflects the latest bake/export every run.
#
# Prereqs:
#   - worker/export/serving.sql + fts5_setup.sql exist
#     (run: python3 scripts/export_serving_db.py --db data/collaboration_network_mb.db)
#   - worker/.dev.vars holds SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
#     (only needed for lazy resolve-track; baked previews work without it)
#
# Usage:  ./scripts/run_local_demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKER="$ROOT/worker"
EXPORT_DIR="$WORKER/export"

if [ ! -f "$EXPORT_DIR/serving.sql" ]; then
  echo "error: $EXPORT_DIR/serving.sql not found." >&2
  echo "  run: python3 scripts/export_serving_db.py --db data/collaboration_network_mb.db" >&2
  exit 1
fi

cd "$WORKER"

echo "→ resetting local D1 (drops stale INSERT-OR-IGNORE data)…"
rm -rf .wrangler/state/v3/d1

echo "→ seeding local D1 from export/serving.sql…"
npx wrangler d1 execute rabbit-hole-serving --local --file=export/serving.sql
echo "→ creating FTS5 search index…"
npx wrangler d1 execute rabbit-hole-serving --local --file=export/fts5_setup.sql

echo "→ starting Worker (:8787) + frontend (:3000) — Ctrl-C to stop both…"
npx wrangler dev --port 8787 &
WORKER_PID=$!
( cd "$ROOT/frontend" && npm run dev ) &
FRONTEND_PID=$!
trap 'kill "$WORKER_PID" "$FRONTEND_PID" 2>/dev/null || true' EXIT INT TERM
wait
