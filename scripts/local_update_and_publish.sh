#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LOG_DIR"

cd "$ROOT"

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and fill Metabase credentials." >&2
  exit 1
fi

set -a
source .env
set +a

python3 scripts/update_data.py

git add dashboard_data.json
if git diff --cached --quiet; then
  echo "No dashboard data change."
  exit 0
fi

git commit -m "chore: refresh dashboard data $(date '+%Y-%m-%d %H:%M:%S')"
git push
